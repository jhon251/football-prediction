# DATA-006: supervisor watchdog (P1-2).  Long-lived, low-privilege recovery
# loop for the line-up capture supervisor.  Started at user logon by the
# Startup entry (install_startup.ps1); no admin rights needed.
#
# Policy (restart ONLY when ALL of these hold):
#   1. no supervisor.py process for this op dir (same CIM match as the
#      launcher's single-instance guard), AND
#   2. heartbeat missing or older than 3 x supervisor poll interval, AND
#   3. no supervisor.stop file (manual maintenance freeze).
#
# The watchdog NEVER creates or modifies capture jobs, state, feed, or the
# capture store.  It only invokes supervisor_launcher.ps1 (which has its own
# single-instance guard) and appends lines to watchdog.log.  The supervisor
# owns all state transitions.
#
#   -Once    : run a single check, print ACTION=<start|skip-*|wait-*>, exit 0
#              (used by tests; normal hard errors exit non-zero)
param(
    [string]$Root = "C:\football",
    [string]$OpDir = "",
    [string]$Store = "",
    [string]$Feed = "",
    [int]$Poll = 60,
    [int]$Interval = 300,
    [switch]$Once
)
$ErrorActionPreference = "Stop"

$defaultOpDir = [System.IO.Path]::GetFullPath(
    (Join-Path $Root "data\lineups\prospective\supervisor"))
$opDir = if ($OpDir) { [System.IO.Path]::GetFullPath($OpDir) } else { $defaultOpDir }
$launcher = Join-Path $Root "scripts\lineup_capture\supervisor_launcher.ps1"
$hbPath = Join-Path $opDir "supervisor_heartbeat.json"
$stopFile = Join-Path $opDir "supervisor.stop"
$wdLog = Join-Path $opDir "watchdog.log"
$staleAfterS = 3 * $Poll

# watchdog.log must be writable even on a brand-new deployment (op dir may
# not exist yet if the supervisor never started).
New-Item -ItemType Directory -Force -Path $opDir | Out-Null

function Get-SupervisorProcess {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object {
            $cl = $_.CommandLine
            ($cl -match "supervisor\.py") -and (
                ($cl -match [regex]::Escape("--op-dir $opDir")) -or
                ($cl -notmatch "--op-dir" -and $opDir -eq $defaultOpDir))
        }
}

function Test-SupervisorRunning {
    return (@(Get-SupervisorProcess).Count -gt 0)
}

function Get-HeartbeatAgeSeconds {
    if (-not (Test-Path $hbPath)) { return $null }
    try {
        $ts = (Get-Content -LiteralPath $hbPath -Raw | ConvertFrom-Json).timestamp
        $t = [datetime]::Parse($ts).ToUniversalTime()
        return ((Get-Date).ToUniversalTime() - $t).TotalSeconds
    } catch {
        return $null  # unreadable/corrupt -> treat as stale
    }
}

function Watchdog-Log {
    param([string]$Msg)
    $line = "{0:o} | {1}" -f (Get-Date).ToUniversalTime(), $Msg
    Add-Content -LiteralPath $wdLog -Value $line -Encoding UTF8
}

function Invoke-WatchdogCheck {
    if (Test-Path $stopFile) {
        Watchdog-Log "skip: supervisor.stop present - manual freeze respected"
        return "skip-stopfile"
    }
    if (Test-SupervisorRunning) {
        Watchdog-Log "skip: supervisor process running"
        return "skip-running"
    }
    $age = Get-HeartbeatAgeSeconds
    if ($null -ne $age -and $age -le $staleAfterS) {
        Watchdog-Log ("wait: no process but heartbeat fresh " +
                      "(age={0:N0}s <= {1}s) - grace period" -f $age, $staleAfterS)
        return "wait-fresh-heartbeat"
    }
    $why = if ($null -eq $age) { "heartbeat missing" }
           else { "heartbeat stale (age={0:N0}s)" -f $age }
    Watchdog-Log "restart: no supervisor process and $why - invoking launcher"
    $launcherArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass",
                      "-File", $launcher, "-OpDir", $opDir, "-Poll", "$Poll")
    if ($Store) { $launcherArgs += @("-Store", $Store) }
    if ($Feed)  { $launcherArgs += @("-Feed", $Feed) }
    # CRITICAL: fire-and-forget via Start-Process WITHOUT output redirection
    # and WITHOUT -Wait.  No redirection means ShellExecute gives the child a
    # FRESH handle table, so the detached long-lived supervisor cannot
    # inherit this captured function's collection pipe (observed hang with
    # both `&` and `-Wait` variants: the pipe's write end stays open in the
    # supervisor and PowerShell waits for EOF forever).  Not waiting is also
    # correct watchdog behaviour: whether the start succeeded is judged by
    # the NEXT cycle's process + heartbeat check, never by this call.
    # The launcher exits in ~1s; the supervisor stays detached.
    $p = Start-Process -FilePath powershell `
        -ArgumentList $launcherArgs `
        -WindowStyle Hidden -PassThru
    Watchdog-Log "restart: launcher invoked pid=$($p.Id)"
    return "start"
}

if ($Once) {
    Write-Output ("ACTION=" + (Invoke-WatchdogCheck))
    exit 0
}

Watchdog-Log ("watchdog started: interval={0}s poll={1}s opDir={2}" -f
              $Interval, $Poll, $opDir)
while ($true) {
    try {
        $null = Invoke-WatchdogCheck
    } catch {
        Watchdog-Log ("error: " + $_.Exception.Message)
    }
    Start-Sleep -Seconds $Interval
}
