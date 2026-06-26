# Setup scheduled task for memory reconciliation
# Run this once as Administrator

$taskName = "MiMoCode-MemoryReconcile"
# Resolve the wrapper next to this script so it works from any clone location.
$scriptPath = Join-Path $PSScriptRoot "reconcile_memory.bat"

# Create scheduled task
$action = New-ScheduledTaskAction -Execute $scriptPath
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 365) -At (Get-Date) -Once
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Reconcile MiMo Code memory FTS index"

Write-Host "Scheduled task '$taskName' created. It will run every 5 minutes."
Write-Host "To run now: Start-ScheduledTask -TaskName '$taskName'"
