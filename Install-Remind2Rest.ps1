# Install-Remind2Rest.ps1

$ErrorActionPreference = "Stop"

Write-Host "╔════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║        Remind2Rest Installer       ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════╝" -ForegroundColor Cyan

$AppDir = "$env:LOCALAPPDATA\Remind2Rest"
$VenvDir = "$AppDir\venv"
$ConfigPath = "$AppDir\reminder_config.json"
$ScriptDir = $PSScriptRoot

# 1. Create Directories
Write-Host "`n[1/5] Creating application directories..." -ForegroundColor Yellow
if (!(Test-Path $AppDir)) { New-Item -ItemType Directory -Path $AppDir | Out-Null }

# 2. Setup Virtual Environment
Write-Host "[2/5] Setting up virtual environment..." -ForegroundColor Yellow
if (!(Test-Path $VenvDir)) {
    python -m venv $VenvDir
}
$PythonExe = "$VenvDir\Scripts\python.exe"
$PipExe = "$VenvDir\Scripts\pip.exe"

# 3. Install Dependencies
Write-Host "[3/5] Installing dependencies..." -ForegroundColor Yellow
& $PipExe install -r "$ScriptDir\requirements.txt"

# 4. Copy Resources
Write-Host "[4/5] Copying resources..." -ForegroundColor Yellow
if (!(Test-Path $ConfigPath)) {
    Copy-Item "$ScriptDir\reminder_config.json" $ConfigPath
}
Copy-Item "$ScriptDir\Remind2Rest.png" "$AppDir\Remind2Rest.png"

# 5. Create Startup Shortcut
Write-Host "[5/5] Creating startup shortcut..." -ForegroundColor Yellow
$WshShell = New-Object -ComObject WScript.Shell
$StartupPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Remind2Rest.lnk"
$Shortcut = $WshShell.CreateShortcut($StartupPath)
$Shortcut.TargetPath = $PythonExe
$Shortcut.Arguments = "`"$ScriptDir\Remind2Rest.py`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.WindowStyle = 7 # Minimized
$Shortcut.IconLocation = "$AppDir\Remind2Rest.png"
$Shortcut.Save()

# Create Desktop Shortcut for Configurator
$DesktopPath = "$env:USERPROFILE\Desktop\Remind2Rest Configurator.lnk"
$ConfigShortcut = $WshShell.CreateShortcut($DesktopPath)
$ConfigShortcut.TargetPath = $PythonExe
$ConfigShortcut.Arguments = "`"$ScriptDir\web_configurator.py`""
$ConfigShortcut.WorkingDirectory = $ScriptDir
$ConfigShortcut.IconLocation = "$AppDir\Remind2Rest.png"
$ConfigShortcut.Save()

Write-Host "`n✅ Installation Complete!" -ForegroundColor Green
Write-Host "Remind2Rest will now start automatically when you log in."
Write-Host "You can find the Configurator on your Desktop."

if ((Read-Host "`nDo you want to start Remind2Rest now? (y/n)") -eq "y") {
    Start-Process $PythonExe -ArgumentList "`"$ScriptDir\Remind2Rest.py`"" -WindowStyle Hidden
    Write-Host "🚀 Remind2Rest started in background."
}
