param(
  [ValidatePattern('^\d{2}:\d{2}$')]
  [string]$DailyAt = '02:10',
  [int]$MaxEntities = 250,
  [string]$BusinessScope = 'all'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'run_viv_daily_dossier_sweep.ps1'
$taskName = 'VIV Daily Dossier Sweep'
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -MaxEntities {1} -BusinessScope "{2}"' -f $runner, $MaxEntities, $BusinessScope

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Output "Registered '$taskName' at $DailyAt local time."
