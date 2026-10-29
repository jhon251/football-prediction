# DATA-006: install/uninstall the long-running capture supervisor as a
# Windows Scheduled Task (single continuous task; per-match capture jobs are
# spawned by the supervisor itself).
#
#   powershell -ExecutionPolicy Bypass -File scripts\lineup_capture\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\lineup_capture\install_task.ps1 -Uninstall
#
# Recommended option (most stable / easiest to maintain): ONE task at startup
# running the supervisor; the supervisor plans and spawns short-lifecycle
# per-match capture jobs from the fixtures feed.  Restart-on-failure is
# configured at the task level (3 restarts, 5-minute interval).
#
# NOTE: this registers the task in the CURRENT USER's own task folder
# ("\<username>\") at the default (least-privilege) run level - it requires
# NO administrator elevation.  It intentionally does not use RunLevel
# Highest (which would force an admin consent prompt) and does not attempt
# any permission bypass.

param([switch]$Uninstall)

$TaskName = "DATA005-LineupCaptureSupervisor"
$UserFolder = "\$env:USERNAME\"
$Script = Join-Path (Get-Location) "scripts\lineup_capture\supervisor_launcher.ps1"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $UserFolder `
        -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "task unregistered: $TaskName (in $UserFolder)"
    exit 0
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory (Get-Location)

$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -AtLogOn)
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -TaskPath $UserFolder `
    -Action $action -Trigger $triggers -Settings $settings `
    -Principal $principal -Force | Out-Null
Write-Output "task registered: $TaskName (in $UserFolder, least-privilege)"
Write-Output "  action : powershell -File $Script"
Write-Output "  start  : user logon (AtLogOn) + at system startup once logged on (AtStartup)"
Write-Output "  restart-on-failure x3 (5 min)"
Write-Output "  verify : Get-ScheduledTask -TaskName $TaskName -TaskPath `"$UserFolder`""
Write-Output "           Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath `"$UserFolder`""
