@echo off
rem House Lights on Windows: set up, start, stop, check the dashboard.
rem Usage:  scripts\windows-dashboard.bat COMMAND     (start, stop, restart, status, logs, run, setup)
rem With no command it shows the help and waits, so double-clicking it explains itself.
rem The work is done by windows-dashboard.ps1 next to this file.
rem   -ExecutionPolicy Bypass applies to that one run only: it does not change your PowerShell settings.
rem   PSModulePath is cleared for that one run (setlocal keeps it from leaking into your window): when
rem   PowerShell 7 is installed, the inherited path points Windows PowerShell 5.1 at PowerShell 7's
rem   modules, and 5.1 then cannot find cmdlets such as Get-FileHash.
setlocal
set "PSModulePath="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-dashboard.ps1" %*
set RC=%ERRORLEVEL%
if "%~1"=="" pause
exit /b %RC%
