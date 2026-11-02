# Install-Remind2Rest.ps1
# Installs Remind2Rest for the current user: a venv in %LOCALAPPDATA%\Remind2Rest, autostart at login,
# shortcuts to the settings window, then (re)starts the background service. Safe to run again to update.

$ErrorActionPreference = "Stop"

Write-Host "--- Remind2Rest Installer ---"

$AppDir = "$env:LOCALAPPDATA\Remind2Rest"
$VenvDir = "$AppDir\venv"
$ConfigPath = "$AppDir\reminder_config.json"
$ScriptDir = $PSScriptRoot
$IconPath = "$ScriptDir\Remind2Rest.ico"
$Port = 55555

function Send-Remind2Rest([string]$Command) {
    # Plain-text command to the running service; returns its reply or $null when none runs.
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $stream = $client.GetStream()
        $bytes = [Text.Encoding]::UTF8.GetBytes($Command)
        $stream.Write($bytes, 0, $bytes.Length)
        $buffer = New-Object byte[] 256
        $stream.ReadTimeout = 3000
        $n = $stream.Read($buffer, 0, $buffer.Length)
        $client.Close()
        return [Text.Encoding]::UTF8.GetString($buffer, 0, $n)
    } catch {
        return $null
    }
}

function Test-Remind2Rest {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

# 1. Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found. Install Python 3.8+ from python.org (with 'Add to PATH') and run this again."
}

# 2. Directories and virtual environment
Write-Host "Setting up the virtual environment in $VenvDir ..."
if (!(Test-Path $AppDir)) { New-Item -ItemType Directory -Path $AppDir | Out-Null }
if (!(Test-Path "$VenvDir\Scripts\python.exe")) {
    python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Creating the virtual environment failed (exit code $LASTEXITCODE)." }
}
$PythonExe = "$VenvDir\Scripts\python.exe"
$PythonW = "$VenvDir\Scripts\pythonw.exe"

# 3. Dependencies. pip's exit code has to be checked by hand: native commands do not stop the script.
Write-Host "Installing dependencies..."
& $PythonExe -m pip install --disable-pip-version-check -r "$ScriptDir\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Installing the dependencies failed (pip exit code $LASTEXITCODE). Nothing was changed." }

# 4. Config: keep an existing one; without one the service writes the defaults on first start.
if (!(Test-Path $ConfigPath) -and (Test-Path "$ScriptDir\reminder_config.json")) {
    Copy-Item "$ScriptDir\reminder_config.json" $ConfigPath
}

# 5. Shortcuts. pythonw.exe: no console window.
Write-Host "Creating shortcuts..."
$WshShell = New-Object -ComObject WScript.Shell
function New-Shortcut([string]$Path, [string]$Script, [string]$Description) {
    $Shortcut = $WshShell.CreateShortcut($Path)
    $Shortcut.TargetPath = $PythonW
    $Shortcut.Arguments = "`"$ScriptDir\$Script`""
    $Shortcut.WorkingDirectory = $ScriptDir
    $Shortcut.IconLocation = $IconPath
    $Shortcut.Description = $Description
    $Shortcut.Save()
}
$Startup = [Environment]::GetFolderPath("Startup")
$Programs = [Environment]::GetFolderPath("Programs")
$Desktop = [Environment]::GetFolderPath("Desktop")
New-Shortcut "$Startup\Remind2Rest.lnk" "Remind2Rest.py" "Remind2Rest background service"
New-Shortcut "$Programs\Remind2Rest.lnk" "configurator.py" "Remind2Rest settings"
New-Shortcut "$Desktop\Remind2Rest Configurator.lnk" "configurator.py" "Remind2Rest settings"

# 6. (Re)start the service, so an update runs the new code.
if (Test-Remind2Rest) {
    Write-Host "Stopping the running Remind2Rest..."
    Send-Remind2Rest "QUIT" | Out-Null
    $deadline = (Get-Date).AddSeconds(10)
    while ((Test-Remind2Rest) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    if (Test-Remind2Rest) {
        # Versions before QUIT existed: end the process directly.
        Get-CimInstance Win32_Process |
            Where-Object { $_.CommandLine -match 'Remind2Rest\.py' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }
    if (Test-Remind2Rest) {
        throw "The running Remind2Rest did not stop. Quit it from the tray icon and run this again."
    }
}
Start-Process $PythonW -ArgumentList "`"$ScriptDir\Remind2Rest.py`"" -WorkingDirectory $ScriptDir
$deadline = (Get-Date).AddSeconds(15)
while (-not (Test-Remind2Rest) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
if (-not (Test-Remind2Rest)) {
    throw "Remind2Rest did not start. See $AppDir\Remind2Rest.log and $AppDir\overlay-errors.log."
}

# 7. Windows 11 puts new tray icons into the overflow menu; pin ours to the taskbar. The entry
#    appears once the icon has been shown, so wait for it a little.
$deadline = (Get-Date).AddSeconds(10)
do {
    $entries = Get-ChildItem "HKCU:\Control Panel\NotifyIconSettings" -ErrorAction SilentlyContinue |
        Where-Object { (Get-ItemProperty $_.PSPath).InitialTooltip -eq "Remind2Rest" }
    if ($entries) { break }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
foreach ($entry in $entries) {
    Set-ItemProperty $entry.PSPath -Name IsPromoted -Value 1 -Type DWord
}

Write-Host "Installation complete. Remind2Rest runs in the tray and starts automatically at login."
Write-Host "Settings: Start menu or desktop shortcut 'Remind2Rest'. Logs: $AppDir"
