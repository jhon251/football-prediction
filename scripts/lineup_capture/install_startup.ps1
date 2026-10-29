# DATA-006: install/uninstall the user-level STARTUP entry (logon auto-start)
# - the fallback for "auto-resume after daily power-off" when the Windows
# Scheduled Task cannot be registered (HRESULT 0x80070005 in this
# environment).  Uses ONLY the current user's Startup folder - no admin,
# no permission bypass.
#
#   powershell -ExecutionPolicy Bypass -File scripts\lineup_capture\install_startup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\lineup_capture\install_startup.ps1 -Uninstall
#
# The Startup entry launches watchdog.ps1 (P1-2): a long-lived recovery loop
# that restarts the supervisor only when its process is gone AND its
# heartbeat is stale AND no supervisor.stop freeze file exists.  The watchdog
# delegates every actual start to supervisor_launcher.ps1, which has its own
# single-instance guard (no duplicate supervisor).  Heartbeat/state/audit
# live under data\lineups\prospective\supervisor\.

param([switch]$Uninstall)

$StartupDir = [Environment]::GetFolderPath("Startup")
$Link = Join-Path $StartupDir "DATA006-LineupCaptureSupervisor.cmd"
$Watchdog = "C:\football\scripts\lineup_capture\watchdog.ps1"

if ($Uninstall) {
    Remove-Item -LiteralPath $Link -Force -ErrorAction SilentlyContinue
    Write-Output "startup entry removed: $Link"
    exit 0
}

if (-not (Test-Path $Watchdog)) {
    Write-Error "watchdog not found: $Watchdog"
    exit 1
}

# .cmd content: start a hidden PowerShell that runs the watchdog loop.
$content = "@echo off`r`n" +
    "start `"DATA006-SupervisorWatchdog`" /min powershell -NoProfile " +
    "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Watchdog`"`r`n"

Set-Content -LiteralPath $Link -Value $content -Encoding Ascii
Write-Output "startup entry installed: $Link"
Write-Output "  runs at every user logon (incl. after daily power-off)"
Write-Output "  launches the watchdog, which supervises the supervisor"
Write-Output "  watchdog restarts only when: no process + stale heartbeat + no stop file"
Write-Output "  verify : Get-Content `"$Link`""
Write-Output "           Test-Path `"$Link`""
