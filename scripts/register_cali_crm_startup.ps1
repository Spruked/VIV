param(
  [Parameter(Mandatory = $true)][string]$Root
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
$launcher = Join-Path $root 'start_cali_crm.bat'
$trayScript = Join-Path $root 'scripts\cali_crm_tray.ps1'
$shortcutPath = Join-Path $env:USERPROFILE 'Desktop\VIV.lnk'
$runRegistryPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runValueName = 'VIV_Autostart'
$pngPath = Join-Path $root 'frontend\public\VIVLOGO.png'
$iconPath = Join-Path $root 'VIV.ico'

if (-not (Test-Path -LiteralPath $trayScript)) {
  throw "VIV tray supervisor not found: $trayScript"
}

# Remove the old CRM-facing startup artifacts so VIV has one desktop identity.
$legacyShortcut = Join-Path $env:USERPROFILE 'Desktop\CALI CRM.lnk'
if (Test-Path -LiteralPath $legacyShortcut) {
  Remove-Item -LiteralPath $legacyShortcut -Force -ErrorAction SilentlyContinue
}
if (Test-Path $runRegistryPath) {
  Remove-ItemProperty -Path $runRegistryPath -Name 'CALI_CRM_Autostart' -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $iconPath) -and (Test-Path -LiteralPath $pngPath)) {
  try {
    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::FromFile($pngPath)
    try {
      $icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
      $stream = New-Object System.IO.FileStream($iconPath, [System.IO.FileMode]::Create)
      try { $icon.Save($stream) } finally { $stream.Dispose() }
    } finally {
      $bitmap.Dispose()
    }
  } catch {
    Write-Warning "Could not create VIV icon: $($_.Exception.Message)"
    $iconPath = $null
  }
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = 'Start VIV - Vector Intelligence Vault'
if ($iconPath -and (Test-Path -LiteralPath $iconPath)) {
  $shortcut.IconLocation = "$iconPath,0"
}
$shortcut.Save()

if (-not (Test-Path $runRegistryPath)) {
  New-Item -Path $runRegistryPath -Force | Out-Null
}
$runCommand = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$trayScript`" -Startup"
Set-ItemProperty -Path $runRegistryPath -Name $runValueName -Value $runCommand

Write-Host "VIV shortcut: $shortcutPath"
Write-Host "VIV startup: $runCommand"
