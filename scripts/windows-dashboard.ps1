# House Lights on Windows: set up, start, stop, check the dashboard.
# Use it through windows-dashboard.bat, next to this file:  scripts\windows-dashboard.bat COMMAND
#
# This file is plain ASCII on purpose: Windows PowerShell 5.1 reads a file without a byte-order
# mark as ANSI, and would garble anything else.
param(
    [string]$Command = "help",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)
$ErrorActionPreference = "Stop"

$Root    = Split-Path -Parent $PSScriptRoot
$Venv    = Join-Path $Root "venv"
$VPy     = Join-Path $Venv "Scripts\python.exe"
$Stamp   = Join-Path $Venv ".requirements-stamp"     # what was installed last: a hash of requirements.txt (+ tinytuya)
$Data    = if ($env:HOUSELIGHTS_HOME) { $env:HOUSELIGHTS_HOME } else { Join-Path $Root "data" }
$PidFile = Join-Path $Data "dashboard.pid"
$LogDir  = Join-Path $Data "logs"
$Log     = Join-Path $LogDir "houselights.log"       # the program's own log file

function Say($text) { Write-Host $text }
function Die($text) { Write-Host "Error: $text" -ForegroundColor Red; exit 1 }

function Show-Usage {
    Say @"
House Lights on Windows.

Usage: scripts\windows-dashboard.bat COMMAND

  start [...]  Set up if needed (checks Python 3.10+, makes venv\, installs requirements.txt),
               then start the dashboard in the background.
               Extra words go to the program: start --dry  is practice mode (nothing is sent
               to the lights; commands are only logged), start --port 8091 uses another port
  stop         Stop it (any animation is taken off the lights first)
  restart      Stop and start it again (use after git pull or a settings change)
  status       Running? What address to open?
  logs         Follow the log (Ctrl+C to leave)
  run [...]    Run it in this window instead: Ctrl+C stops it. Same extra words as start.
  setup        Only the setup part of start (Python, venv\, requirements)

It does not start by itself when Windows starts. Settings are kept in data\ (config.json and
more); this script never touches them.
"@
}

# --- Python, venv, requirements --------------------------------------------------------------------
function Test-Python($exe, $pre) {
    try {
        & $exe @pre -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# The first Python 3.10 or newer: $env:PYTHON if you set it, else the py launcher (3.13 ... 3.10), python, python3.
function Find-Python {
    $candidates = @()
    if ($env:PYTHON) { $candidates += , @($env:PYTHON) }
    foreach ($v in "3.13", "3.12", "3.11", "3.10") { $candidates += , @("py", "-$v") }
    $candidates += , @("python")
    $candidates += , @("python3")
    foreach ($c in $candidates) {
        $exe = $c[0]
        $pre = @($c | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        if (Test-Python $exe $pre) { return @{ Exe = $exe; Pre = $pre } }
    }
    return $null
}

# Tuya / Smart Life lights need the optional tinytuya package; install it when the settings use one.
function Test-UsesTuya {
    $cfg = Join-Path $Data "config.json"
    return ((Test-Path $cfg) -and ((Get-Content $cfg -Raw) -match '"type"\s*:\s*"tuya"'))
}

function Get-Fingerprint {
    $h = (Get-FileHash (Join-Path $Root "requirements.txt") -Algorithm SHA256).Hash
    if (Test-UsesTuya) { $h += "+tinytuya" }
    return $h
}

# Everything the dashboard needs before it can start. Safe to run any number of times.
function Initialize-Environment {
    Set-Location $Root
    if (-not (Test-Path (Join-Path $Root "requirements.txt"))) {
        Die "requirements.txt not found in $Root. Run this script from a House Lights folder."
    }
    $py = Find-Python
    if (-not $py) {
        Die ("House Lights needs Python 3.10 or newer, and none was found.`n" +
             "  Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), or run: winget install Python.Python.3.12`n" +
             "  Then run this again. To use a Python somewhere else: set PYTHON=C:\path\to\python.exe")
    }
    # A venv\ that is incomplete (its Python is missing) or has an old Python is made again, but only
    # when it really is a virtual environment (it has pyvenv.cfg); anything else is yours.
    if (Test-Path $Venv) {
        if (-not (Test-Path $VPy) -or -not (Test-Python $VPy @())) {
            if (-not (Test-Path (Join-Path $Venv "pyvenv.cfg"))) {
                Die "$Venv exists but is not a Python virtual environment. Move or delete it, then run this again."
            }
            Say "The virtual environment in venv\ is broken or has an old Python: making it again."
            Remove-Item -Recurse -Force $Venv
        }
    }
    if (-not (Test-Path $VPy)) {
        Say "Making the virtual environment (venv\) ..."
        $pre = $py.Pre
        & $py.Exe @pre -m venv $Venv
        if ($LASTEXITCODE -ne 0) { Die "Could not make the virtual environment." }
        if (-not (Test-Python $VPy @())) { Die "The virtual environment was made, but its Python does not run: $VPy" }
    }
    $want = Get-Fingerprint
    $have = ""
    if (Test-Path $Stamp) { $have = (Get-Content $Stamp -Raw).Trim() }
    if ($want -ne $have) {
        Say "Installing what House Lights needs (first time, or requirements.txt changed) ..."
        & $VPy -m pip install --disable-pip-version-check -r (Join-Path $Root "requirements.txt")
        if ($LASTEXITCODE -ne 0) { Die "Installing requirements.txt failed." }
        if (Test-UsesTuya) {
            Say "Your settings use Tuya / Smart Life lights: installing tinytuya too."
            & $VPy -m pip install --disable-pip-version-check tinytuya
            if ($LASTEXITCODE -ne 0) { Die "Installing tinytuya failed." }
        }
        Set-Content -Path $Stamp -Value $want
    }
}

# --- the running dashboard -------------------------------------------------------------------------
function Get-ConfiguredPort {
    try {
        $port = (Get-Content (Join-Path $Data "config.json") -Raw | ConvertFrom-Json).listen.port
        if ($port) { return [int]$port }
    } catch { }
    return 8090
}

# The process id from the pid file, if that process is alive and really House Lights.
function Get-RunningId {
    if (-not (Test-Path $PidFile)) { return $null }
    try {
        $id = [int](Get-Content $PidFile -TotalCount 1)
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $id" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -match "houselights") { return $id }
    } catch { }
    return $null
}

# The port it listens on: the one it was started with (--port N), else the one in the settings.
function Get-RunningPort($id) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $id" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -match "--port\s+(\d+)") { return [int]$Matches[1] }
    return Get-ConfiguredPort
}

function Show-Address($id) {
    $port = Get-RunningPort $id
    Say "Open:  http://localhost:$port/"
    try {
        $ip = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object { $_.AddressFamily -eq "InterNetwork" -and -not $_.ToString().StartsWith("169.254") } |
            Select-Object -First 1
        if ($ip) { Say "From your phone on the same Wi-Fi:  http://${ip}:$port/" }
    } catch { }
}

function Start-Dashboard {
    Initialize-Environment
    $id = Get-RunningId
    if ($id) {
        Say "House Lights is already running (process $id)."
        Show-Address $id
        return
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $argList = @("-m", "houselights")
    if ($Rest) { $argList += $Rest }
    $argList = @($argList | ForEach-Object { if ($_ -match "\s") { '"' + $_ + '"' } else { $_ } })
    $p = Start-Process -FilePath $VPy -ArgumentList $argList -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "console.log") `
        -RedirectStandardError (Join-Path $LogDir "console-error.log") -PassThru
    Set-Content -Path $PidFile -Value $p.Id
    Start-Sleep -Seconds 4
    $id = Get-RunningId
    if ($id) {
        Say "House Lights is running."
        Show-Address $id
    } else {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        Say "House Lights did not stay up. The last lines it printed:"
        foreach ($f in "console-error.log", "console.log") {
            $file = Join-Path $LogDir $f
            if (Test-Path $file) { Get-Content $file -Tail 15 }
        }
        Die "The lines above say why. (A copy started with 'run' in another window would also be a reason: close it with Ctrl+C.)"
    }
}

function Stop-Dashboard {
    $id = Get-RunningId
    if (-not $id) {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        Say "House Lights is not running."
        return
    }
    $port = Get-RunningPort $id
    # A background Windows process can't be asked to shut down politely, so first do what a polite
    # shutdown does: stop any animation (it is taken off the controllers). It can't when a password
    # is set; then an animation keeps its last picture until you pick something else.
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/stop-all" -Method Post -ContentType "application/json" -Body "{}" -TimeoutSec 4 | Out-Null
    } catch {
        Say "(Could not stop any animation first; one that was playing keeps its last picture until you pick something else.)"
    }
    & taskkill.exe /PID $id /T /F | Out-Null
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    Say "Stopped."
}

function Show-Status {
    $id = Get-RunningId
    if ($id) {
        Say "Running:  yes (process $id)"
        Show-Address $id
    } else {
        Say "Running:  no"
    }
    if (Test-Path $Log) { Say ""; Get-Content $Log -Tail 5 }
}

switch ($Command.ToLower()) {
    "start"   { Start-Dashboard }
    "stop"    { Stop-Dashboard }
    "restart" { Stop-Dashboard; Start-Dashboard }
    "status"  { Show-Status }
    "logs" {
        if (-not (Test-Path $Log)) { Die "No log yet: $Log. Start it first." }
        Get-Content $Log -Tail 50 -Wait
    }
    "run" {
        Initialize-Environment
        if (Get-RunningId) {
            Say "Note: House Lights is already running in the background, so this copy cannot use the same port."
            Say "      Run 'scripts\windows-dashboard.bat stop' first, or add --port 8091."
        }
        & $VPy -m houselights @Rest
    }
    "setup"   { Initialize-Environment; Say "Ready: Python, venv\ and requirements are in place." }
    { $_ -in "help", "-h", "--help", "/?" } { Show-Usage }
    default   { Say "Unknown command: $Command"; Say ""; Show-Usage; exit 2 }
}
