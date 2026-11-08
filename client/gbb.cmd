@echo off
REM gbb - client for the Bot Bridge (Windows).
REM   gbb status
REM   gbb get_page
REM   gbb click index=3
REM   gbb type index=1 "text=hello world" submit=true
setlocal
set "BRIDGE=%~dp0..\bridge\bridge.py"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
if "%~1"=="status"    goto direct
if "%~1"=="token"     goto direct
if "%~1"=="serve"     goto direct
if "%~1"=="new-token" goto direct
%PY% "%BRIDGE%" send %*
goto :eof
:direct
%PY% "%BRIDGE%" %*
