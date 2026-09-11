param(
  [int]$MaxEntities = 250,
  [string]$BusinessScope = 'all'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$healthUrl = 'http://127.0.0.1:21000/health'
$sweepUrl = 'http://127.0.0.1:21000/cali/intelligence/automation/daily-dossier-sweep'

function Test-VivBackend {
  try {
    return (Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3).status -eq 'ok'
  } catch {
    return $false
  }
}

if (-not (Test-VivBackend)) {
  Start-Process -FilePath (Join-Path $root 'start_cali_crm.bat') -WorkingDirectory $root -WindowStyle Hidden
  $deadline = (Get-Date).AddSeconds(90)
  while ((Get-Date) -lt $deadline -and -not (Test-VivBackend)) {
    Start-Sleep -Seconds 3
  }
}

if (-not (Test-VivBackend)) {
  throw 'VIV backend did not become healthy on 127.0.0.1:21000.'
}

$payload = @{
  business_scope = $BusinessScope
  max_entities = [Math]::Min(2500, [Math]::Max(1, $MaxEntities))
  run_relationship_scan = $true
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri $sweepUrl -ContentType 'application/json' -Body $payload
