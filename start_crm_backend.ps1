$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $root '.env'
$envExample = Join-Path $root '.env.example'
$requirements = Join-Path $root 'requirements.txt'
$venvDir = Join-Path $root 'venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$appPath = Join-Path $root 'source\cali_skg\api\app.py'

if (-not (Test-Path -LiteralPath $envFile)) {
  if (-not (Test-Path -LiteralPath $envExample)) {
    throw "VIV environment template not found: $envExample"
  }
  Copy-Item -LiteralPath $envExample -Destination $envFile
}

Get-Content -LiteralPath $envFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) {
    return
  }
  $parts = $line.Split('=', 2)
  Set-Item -Path ('Env:' + $parts[0]) -Value $parts[1]
}

# VIV is a Windows-native project. Preserve compatibility with older .env files
# that stored WSL-style mounted-drive paths by translating them at launch time.
$caliDataRoot = [string]$env:CALI_DATA_ROOT
if ($caliDataRoot -match '^/mnt/([a-zA-Z])/(.*)$') {
  $drive = $Matches[1].ToUpper()
  $rest = $Matches[2] -replace '/', '\\'
  $env:CALI_DATA_ROOT = "${drive}:\$rest"
}

if (-not $env:CALI_CRM_PORT) { $env:CALI_CRM_PORT = '21000' }
if (-not $env:PRIME_MAIL_API_URL) { $env:PRIME_MAIL_API_URL = 'http://127.0.0.1:19000/api' }
if (-not $env:SPRUK_EMAIL_API_URL) { $env:SPRUK_EMAIL_API_URL = $env:PRIME_MAIL_API_URL }
$env:PYTHONPATH = Join-Path $root 'source'

function Test-VivPython([string]$PythonPath) {
  if (-not (Test-Path -LiteralPath $PythonPath)) { return $false }
  try {
    & $PythonPath -c "import fastapi, uvicorn, httpx, pydantic" *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
  $bootstrap = $null
  if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $bootstrap = 'py.exe'
    & $bootstrap -3 -m venv $venvDir
  } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    $bootstrap = 'python.exe'
    & $bootstrap -m venv $venvDir
  } else {
    throw 'VIV could not find a Windows Python interpreter to create its local venv.'
  }
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
    throw "VIV failed to create its local Python environment at $venvDir"
  }
}

if (-not (Test-VivPython $venvPython)) {
  if (-not (Test-Path -LiteralPath $requirements)) {
    throw "VIV requirements file not found: $requirements"
  }
  & $venvPython -m pip install -r $requirements
  if ($LASTEXITCODE -ne 0) {
    throw 'VIV dependency installation failed.'
  }
}

if (-not (Test-VivPython $venvPython)) {
  throw 'VIV local Python environment is missing required backend dependencies.'
}

& $venvPython $appPath
exit $LASTEXITCODE
