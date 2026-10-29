# DATA-006: supervisor launcher (used by the Windows Scheduled Task AND the
# user-level Startup entry, via watchdog.ps1).  Starts the long-lived
# supervisor DETACHED: Start-Process -WindowStyle Hidden gives the child its
# own (hidden) console, so Ctrl+C in the caller's console - or the caller
# exiting - does NOT kill the supervisor.  stdout/stderr are captured to
# launcher.out.log / launcher.err.log inside the op dir.
#
# CALLER HAZARD: invoke this script only with its output going to a FILE or
# console - never capture its output into a PowerShell pipeline.  The
# detached supervisor inherits a copy of this script's stdout handle; if
# that handle is a pipe being collected, PowerShell waits for EOF that never
# comes (the supervisor is long-lived) and the caller hangs.  The watchdog
# redirects this script's output to launcher_invoke.log for exactly this
# reason.
#
# Single-instance guard (per op dir): if a supervisor.py process for the SAME
# op dir is already running, exit WITHOUT starting a second one (no duplicate
# scheduling).  A legacy instance started without --op-dir counts as running
# for the default op dir.
param(
    [string]$Root = "C:\football",
    [string]$OpDir = "",
    [string]$Store = "",
    [string]$Feed = "",
    [int]$Poll = 60,
    [int]$MaxRestarts = 3
)
$ErrorActionPreference = "Stop"

$defaultOpDir = [System.IO.Path]::GetFullPath(
    (Join-Path $Root "data\lineups\prospective\supervisor"))
$opDir = if ($OpDir) { [System.IO.Path]::GetFullPath($OpDir) } else { $defaultOpDir }

# Guard: any python.exe whose command line is this supervisor with this op dir.
$existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object {
        $cl = $_.CommandLine
        ($cl -match "supervisor\.py") -and (
            ($cl -match [regex]::Escape("--op-dir $opDir")) -or
            ($cl -notmatch "--op-dir" -and $opDir -eq $defaultOpDir))
    }
if ($existing) {
    Write-Output ("supervisor already running for this op-dir " +
                  "(pid=$($existing.ProcessId)); exit without starting another")
    exit 0
}

New-Item -ItemType Directory -Force -Path $opDir | Out-Null
$cmd = Join-Path $Root "scripts\lineup_capture\supervisor.py"
$outLog = Join-Path $opDir "launcher.out.log"
$errLog = Join-Path $opDir "launcher.err.log"

$args = @($cmd, "--run-forever", "--poll", "$Poll",
          "--max-restarts", "$MaxRestarts", "--op-dir", $opDir)
if ($Store) { $args += @("--store", $Store) }
if ($Feed)  { $args += @("--feed", $Feed) }

# Detached start: new hidden console -> immune to caller's Ctrl+C; the caller
# may exit immediately and the supervisor keeps running unattended.
$p = Start-Process -FilePath (Get-Command python).Source `
    -ArgumentList $args `
    -WorkingDirectory $Root -WindowStyle Hidden `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
Write-Output "supervisor launched detached: pid=$($p.Id)"
