@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0scripts\windows.ps1" -Action Connect %*
set "result=%errorlevel%"
pause
exit /b %result%
