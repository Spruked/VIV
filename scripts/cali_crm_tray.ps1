param(
  [switch]$Startup
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class VivCrmNativeIcon {
  [DllImport("user32.dll")]
  public static extern bool DestroyIcon(IntPtr handle);
}
'@

$root = Split-Path -Parent $PSScriptRoot
$backendScript = Join-Path $root 'start_crm_backend.ps1'
$frontendScript = Join-Path $root 'start_crm_frontend.ps1'
$iconPath = Join-Path $root 'frontend\public\VIVLOGO.png'
$logDir = Join-Path $env:LOCALAPPDATA 'VIV'
$logFile = Join-Path $logDir 'tray.log'
$vivUri = 'http://127.0.0.1:21010'

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-TrayLog([string]$Message) {
  try {
    Add-Content -LiteralPath $logFile -Value ("{0:u} {1}" -f (Get-Date), $Message) -Encoding UTF8
  } catch {}
}

function Get-PngTrayIcon([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  $bitmap = $null
  $sourceIcon = $null
  $handle = [IntPtr]::Zero
  try {
    $bitmap = New-Object System.Drawing.Bitmap($Path)
    $handle = $bitmap.GetHicon()
    $sourceIcon = [System.Drawing.Icon]::FromHandle($handle)
    return $sourceIcon.Clone()
  } catch {
    Write-TrayLog "Tray icon load failed: $($_.Exception.Message)"
    return $null
  } finally {
    if ($sourceIcon) { $sourceIcon.Dispose() }
    if ($handle -ne [IntPtr]::Zero) { [void][VivCrmNativeIcon]::DestroyIcon($handle) }
    if ($bitmap) { $bitmap.Dispose() }
  }
}

$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\CaliCrmTraySupervisor', [ref]$createdNew)
if (-not $createdNew) {
  if (-not $Startup) {
    try { Start-Process $vivUri | Out-Null } catch {}
  }
  exit 0
}

function Test-VivPort([int]$Port) {
  try {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1)
  } catch {
    return $false
  }
}

function Start-VivBackend {
  if (Test-VivPort 21000) { return }
  if (-not (Test-Path -LiteralPath $backendScript)) {
    Write-TrayLog "VIV backend launcher missing: $backendScript"
    return
  }
  Write-TrayLog 'Starting VIV backend.'
  Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $backendScript)) `
    -WorkingDirectory $root `
    -WindowStyle Hidden | Out-Null
}

function Start-VivFrontend {
  if (Test-VivPort 21010) { return }
  if (-not (Test-Path -LiteralPath $frontendScript)) {
    Write-TrayLog "VIV frontend launcher missing: $frontendScript"
    return
  }
  Write-TrayLog 'Starting VIV frontend.'
  Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $frontendScript)) `
    -WorkingDirectory $root `
    -WindowStyle Hidden | Out-Null
}

function Ensure-VivServices {
  Start-VivBackend
  Start-VivFrontend
}

function Open-Viv {
  try { Start-Process $vivUri | Out-Null } catch { Write-TrayLog "Open browser failed: $($_.Exception.Message)" }
}

[System.Windows.Forms.Application]::EnableVisualStyles()
$notify = New-Object System.Windows.Forms.NotifyIcon
$trayIcon = Get-PngTrayIcon $iconPath
if ($trayIcon) {
  $notify.Icon = $trayIcon
} else {
  $notify.Icon = [System.Drawing.SystemIcons]::Information
}
$notify.Text = 'VIV'
$notify.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$statusItem = New-Object System.Windows.Forms.ToolStripMenuItem
$statusItem.Enabled = $false
[void]$menu.Items.Add($statusItem)

$openItem = New-Object System.Windows.Forms.ToolStripMenuItem('Open VIV')
$openItem.Add_Click({ Open-Viv })
[void]$menu.Items.Add($openItem)

$ensureItem = New-Object System.Windows.Forms.ToolStripMenuItem('Ensure VIV services running')
$ensureItem.Add_Click({ Ensure-VivServices })
[void]$menu.Items.Add($ensureItem)

$logsItem = New-Object System.Windows.Forms.ToolStripMenuItem('Open startup log')
$logsItem.Add_Click({
  if (Test-Path -LiteralPath $logFile) { Start-Process notepad.exe -ArgumentList ('"{0}"' -f $logFile) | Out-Null }
})
[void]$menu.Items.Add($logsItem)

[void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
$exitItem = New-Object System.Windows.Forms.ToolStripMenuItem('Exit VIV tray')
$exitItem.Add_Click({
  $notify.Visible = $false
  [System.Windows.Forms.Application]::Exit()
})
[void]$menu.Items.Add($exitItem)

$notify.ContextMenuStrip = $menu
$notify.Add_DoubleClick({ Open-Viv })

function Update-Status {
  $backendReady = Test-VivPort 21000
  $frontendReady = Test-VivPort 21010
  if ($backendReady -and $frontendReady) {
    $statusItem.Text = 'Status: VIV running'
    $notify.Text = 'VIV - running'
  } elseif ($backendReady -or $frontendReady) {
    $statusItem.Text = 'Status: VIV partially running'
    $notify.Text = 'VIV - partial'
  } else {
    $statusItem.Text = 'Status: VIV stopped'
    $notify.Text = 'VIV - stopped'
  }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 5000
$timer.Add_Tick({ Update-Status })

try {
  Ensure-VivServices
  Update-Status
  $timer.Start()
  Write-TrayLog "VIV tray supervisor active. Startup=$Startup"
  [System.Windows.Forms.Application]::Run()
} finally {
  try { $timer.Stop(); $timer.Dispose() } catch {}
  try { $notify.Visible = $false; $notify.Dispose() } catch {}
  try { if ($trayIcon) { $trayIcon.Dispose() } } catch {}
  try { $mutex.ReleaseMutex(); $mutex.Dispose() } catch {}
}
