# finch-epm IT Deployment Script
# ================================
# Run this script as administrator on target machines to install finch-epm.
# Can be pushed via Intune, SCCM, GPO, or run manually.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File deploy.ps1
#
# What it does:
#   1. Checks for Python 3.10+ (installs if missing via winget)
#   2. Installs finch-epm via pip
#   3. Registers .fdash file association
#   4. Sets up scheduled sync task (every 15 minutes)
#   5. Creates desktop shortcut for the setup wizard

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  finch-epm deployment" -ForegroundColor Cyan
Write-Host "  ====================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check Python
Write-Host "  Checking Python installation..." -ForegroundColor Yellow

$python = $null
foreach ($cmd in @("python3", "python", "py")) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $python = $cmd
                Write-Host "  Found $version ($cmd)" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Host "  Python 3.10+ not found. Installing via winget..." -ForegroundColor Yellow
    try {
        winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        $python = "python"
        Write-Host "  Python installed." -ForegroundColor Green
    } catch {
        Write-Host "  ERROR: Could not install Python. Install manually from python.org" -ForegroundColor Red
        exit 1
    }
}

# Step 2: Install finch-epm
Write-Host ""
Write-Host "  Installing finch-epm..." -ForegroundColor Yellow

& $python -m pip install --upgrade pip 2>&1 | Out-Null
& $python -m pip install finch-epm 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: pip install failed." -ForegroundColor Red
    exit 1
}

Write-Host "  finch-epm installed." -ForegroundColor Green

# Step 3: Install optional connectors
Write-Host ""
Write-Host "  Installing optional connectors..." -ForegroundColor Yellow

# SQL Server (most common)
& $python -m pip install "finch-epm[sqlserver]" 2>&1 | Out-Null
Write-Host "  SQL Server connector: installed" -ForegroundColor Green

# Step 4: Register .fdash file association
Write-Host ""
Write-Host "  Registering .fdash file association..." -ForegroundColor Yellow

$pythonPath = (Get-Command $python).Source
$regScript = @"
import sys
sys.argv = ['register', '--exe', r'$pythonPath']
exec(open(r'installer/register_fdash.py').read())
"@

try {
    # Register for current user (no admin needed)
    New-Item -Path "HKCU:\Software\Classes\.fdash" -Force | Out-Null
    Set-ItemProperty -Path "HKCU:\Software\Classes\.fdash" -Name "(Default)" -Value "finch-epm.fdash"

    New-Item -Path "HKCU:\Software\Classes\finch-epm.fdash" -Force | Out-Null
    Set-ItemProperty -Path "HKCU:\Software\Classes\finch-epm.fdash" -Name "(Default)" -Value "finch-epm Dashboard"

    New-Item -Path "HKCU:\Software\Classes\finch-epm.fdash\shell\open\command" -Force | Out-Null
    Set-ItemProperty -Path "HKCU:\Software\Classes\finch-epm.fdash\shell\open\command" -Name "(Default)" -Value "`"$pythonPath`" -m finch_epm.cli.main open `"%1`""

    Write-Host "  .fdash file association: registered" -ForegroundColor Green
} catch {
    Write-Host "  .fdash file association: skipped (non-critical)" -ForegroundColor Yellow
}

# Step 5: Set up scheduled sync
Write-Host ""
Write-Host "  Setting up scheduled sync..." -ForegroundColor Yellow

$taskName = "finch-epm-sync"
$taskAction = New-ScheduledTaskAction -Execute $pythonPath -Argument "-m finch_epm.cli.main service --once"
$taskTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 365)
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries

try {
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Force | Out-Null
    Write-Host "  Scheduled sync: registered (every 15 minutes)" -ForegroundColor Green
} catch {
    Write-Host "  Scheduled sync: skipped (may need admin)" -ForegroundColor Yellow
    Write-Host "  Manual alternative: finch-epm service --interval 15" -ForegroundColor Yellow
}

# Step 6: Create desktop shortcut
Write-Host ""
Write-Host "  Creating desktop shortcut..." -ForegroundColor Yellow

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "finch-epm Setup.lnk"

try {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonPath
    $shortcut.Arguments = "-m finch_epm.cli.main setup"
    $shortcut.Description = "finch-epm: Connect your data sources and build dashboards"
    $shortcut.Save()
    Write-Host "  Desktop shortcut: created" -ForegroundColor Green
} catch {
    Write-Host "  Desktop shortcut: skipped" -ForegroundColor Yellow
}

# Done
Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "  Deployment complete." -ForegroundColor Cyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  The user should now:" -ForegroundColor White
Write-Host "    1. Double-click 'finch-epm Setup' on their desktop" -ForegroundColor White
Write-Host "    2. Follow the wizard to connect their data sources" -ForegroundColor White
Write-Host "    3. Open .fdash dashboard files (double-click or finch-epm open)" -ForegroundColor White
Write-Host ""
Write-Host "  IT notes:" -ForegroundColor Gray
Write-Host "    - Credentials stored in Windows Credential Manager (per-user)" -ForegroundColor Gray
Write-Host "    - Data cached in %LOCALAPPDATA%\finch-epm\" -ForegroundColor Gray
Write-Host "    - Sync runs every 15 minutes via Task Scheduler" -ForegroundColor Gray
Write-Host "    - No admin rights needed for daily use" -ForegroundColor Gray
Write-Host "    - Uninstall: pip uninstall finch-epm" -ForegroundColor Gray
Write-Host ""
