# Install-Remind2Rest.ps1

$ErrorActionPreference = "Stop"

Write-Host "--- Remind2Rest Installer ---"

$AppDir = "$env:LOCALAPPDATA\Remind2Rest"
$VenvDir = "$AppDir\venv"
$ConfigPath = "$AppDir\reminder_config.json"
$ScriptDir = $PSScriptRoot

# 1. Create Directories
Write-Host "Creating application directories..."
if (!(Test-Path $AppDir)) { New-Item -ItemType Directory -Path $AppDir | Out-Null }

# 2. Setup Virtual Environment
Write-Host "Setting up virtual environment..."
if (!(Test-Path $VenvDir)) {
    python -m venv $VenvDir
}
$PythonExe = "$VenvDir\Scripts\python.exe"
$PipExe = "$VenvDir\Scripts\pip.exe"

# 3. Install Dependencies
Write-Host "Installing dependencies..."
& $PipExe install -r "$ScriptDir\requirements.txt"

# 4. Copy Resources
Write-Host "Copying resources..."
if (!(Test-Path $ConfigPath)) {
    Copy-Item "$ScriptDir\reminder_config.json" $ConfigPath
}
Copy-Item "$ScriptDir\Remind2Rest.png" "$AppDir\Remind2Rest.png"

# 5. Create Startup Shortcut
Write-Host "Creating startup shortcut..."
$WshShell = New-Object -ComObject WScript.Shell
$StartupPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Remind2Rest.lnk"
$Shortcut = $WshShell.CreateShortcut($StartupPath)
$Shortcut.TargetPath = $PythonExe
$Shortcut.Arguments = "`"$ScriptDir\Remind2Rest.py`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.WindowStyle = 7
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

Write-Host "Installation Complete!"
Write-Host "Remind2Rest will now start automatically when you log in."

# For non-interactive installer, we just start it.
Start-Process $PythonExe -ArgumentList "`"$ScriptDir\Remind2Rest.py`"" -WindowStyle Hidden
Write-Host "Remind2Rest started in background."
