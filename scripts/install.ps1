# Legoliv Data Logger - installer
# Installs Python, Telegram Desktop, Power BI Desktop and the bot's Python libraries.
# Already-installed programs are detected and skipped. Use -CheckOnly to only report.
param([switch]$CheckOnly)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot

function Say($msg, $color = 'White') { Write-Host $msg -ForegroundColor $color }
function Step($n, $msg) { Write-Host ""; Say "[$n] $msg" Cyan }

Say "============================================================" Green
Say "  Legoliv Data Logger - Installer" Green
Say "============================================================" Green

# ---- winget -----------------------------------------------------
Step 1 "Checking winget (Windows package installer)"
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    Say "winget was not found. Install 'App Installer' from the Microsoft Store, then run this again." Red
    Say "Or install the programs manually - see docs/INSTALLATION.md." Yellow
    if (-not $CheckOnly) { exit 1 }
}
else { Say "winget found." Green }

function Test-Python {
    foreach ($cmd in @('py -3', 'python')) {
        try {
            $parts = $cmd.Split(' ')
            $v = & $parts[0] $parts[1..($parts.Length)] --version 2>$null
            if ($LASTEXITCODE -eq 0 -and "$v" -match 'Python 3\.(\d+)') { if ([int]$Matches[1] -ge 9) { return $cmd } }
        } catch { }
    }
    return $null
}
function Test-AppInstalled($namePattern) {
    $keys = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
    foreach ($k in $keys) {
        if (Get-ItemProperty $k -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like $namePattern }) { return $true }
    }
    return $false
}

# ---- Python -----------------------------------------------------
Step 2 "Python 3 (runs the bot)"
$pyCmd = Test-Python
if ($pyCmd) { Say "Already installed: $((Invoke-Expression "$pyCmd --version"))" Green }
elseif ($CheckOnly) { Say "MISSING - would install Python 3.12" Yellow }
else {
    Say "Installing Python 3.12 ..." Yellow
    winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $pyCmd = Test-Python
    if ($pyCmd) { Say "Python installed." Green } else { Say "Python was installed but is not visible yet. Close this window and run INSTALL.bat again." Yellow }
}

# ---- Telegram ---------------------------------------------------
Step 3 "Telegram Desktop (the lecturer and students use it to talk to the bot)"
$tgPath = Join-Path $env:APPDATA 'Telegram Desktop\Telegram.exe'
if ((Test-Path $tgPath) -or (Test-AppInstalled '*Telegram*')) { Say "Already installed." Green }
elseif ($CheckOnly) { Say "MISSING - would install Telegram Desktop" Yellow }
else {
    Say "Installing Telegram Desktop ..." Yellow
    winget install --id Telegram.TelegramDesktop --exact --silent --accept-package-agreements --accept-source-agreements
}

# ---- Power BI Desktop ------------------------------------------
Step 4 "Power BI Desktop (shows the live dashboard)"
if ((Test-AppInstalled '*Power BI Desktop*') -or (Test-Path "$env:ProgramFiles\Microsoft Power BI Desktop\bin\PBIDesktop.exe")) { Say "Already installed." Green }
elseif ($CheckOnly) { Say "MISSING - would install Power BI Desktop (Microsoft Store)" Yellow }
else {
    Say "Installing Power BI Desktop from the Microsoft Store ..." Yellow
    winget install --id 9NTXR16HNW1T --source msstore --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Say "Automatic install did not finish. Opening the Microsoft Store page - click 'Get'." Yellow
        Start-Process 'ms-windows-store://pdp/?productid=9NTXR16HNW1T'
    }
}

# ---- Python libraries ------------------------------------------
Step 5 "Python libraries for the bot (pyTelegramBotAPI, requests)"
if ($CheckOnly) { Say "Skipped in check-only mode." Yellow }
elseif (-not $pyCmd) { Say "Skipped (Python not ready yet)." Yellow }
else {
    $parts = $pyCmd.Split(' ')
    & $parts[0] $parts[1..($parts.Length)] -m pip install --disable-pip-version-check -r (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE -eq 0) { Say "Libraries ready." Green } else { Say "pip reported a problem - check your internet connection and run again." Red }
}

# ---- Settings file ---------------------------------------------
Step 6 "Settings file (config.ini)"
$cfg = Join-Path $root 'config.ini'
if (Test-Path $cfg) { Say "config.ini already exists - left unchanged." Green }
elseif ($CheckOnly) { Say "Would create config.ini from config.ini.example" Yellow }
else {
    Copy-Item (Join-Path $root 'config.ini.example') $cfg
    Say "Created config.ini. The bot will ask for the Telegram token and Push URL on first start." Green
}

# ---- Desktop shortcut -------------------------------------------
Step 7 "Desktop shortcut (start the bot with one double-click)"
$shortcutOk = $false
if ($CheckOnly) { Say "Would add the shortcut 'Legoliv Data Logger' to the Desktop" Yellow }
else {
    try {
        $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Legoliv Data Logger.lnk'))
        $lnk.TargetPath = Join-Path $root 'START_BOT.bat'
        $lnk.WorkingDirectory = $root
        $lnk.Description = 'Start the Legoliv Data Logger bot'
        $icon = Join-Path $PSScriptRoot 'legoliv.ico'
        if (Test-Path $icon) { $lnk.IconLocation = $icon }
        $lnk.Save()
        $shortcutOk = $true
        Say "Shortcut 'Legoliv Data Logger' added to your Desktop." Green
    } catch {
        Say "Could not create the Desktop shortcut ($($_.Exception.Message)). You can still double-click START_BOT.bat." Yellow
    }
}

# ---- Done -------------------------------------------------------
Write-Host ""
Say "============================================================" Green
Say "  Finished." Green
Say "  Next:  1) Do the one-time Power BI setup  -> docs/POWERBI_SETUP.md" Green
if ($shortcutOk) { Say "         2) Double-click the 'Legoliv Data Logger' shortcut on your Desktop" Green }
else { Say "         2) Double-click START_BOT.bat" Green }
Say "  The bot link for students:  see docs/USER_GUIDE.md" Green
Say "============================================================" Green
