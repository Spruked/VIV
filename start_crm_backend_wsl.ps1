$ErrorActionPreference = 'Stop'

# Compatibility shim retained for older shortcuts/scripts. VIV is Windows-native;
# do not launch it through WSL or borrow a Python environment from another project.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$windowsLauncher = Join-Path $root 'start_crm_backend.ps1'

if (-not (Test-Path -LiteralPath $windowsLauncher)) {
  throw "VIV Windows backend launcher not found: $windowsLauncher"
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $windowsLauncher
exit $LASTEXITCODE
