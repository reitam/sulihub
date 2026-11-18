@echo off
title SuliHub - inditas
chcp 65001 >nul
cd /d "%~dp0"

rem Python valasztas: projekt venv, kulonben a telepitett 3.14, kulonben PATH.
set "PYTHON_EXE=C:\Python314\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo ===================================================
echo   SuliHub - helyi inditas
echo ===================================================
echo Python: %PYTHON_EXE%
echo Adatok: %~dp0data
echo.

if not exist "%~dp0data\config.json" (
    echo HIBA: nem talalhato a data\config.json!
    echo A config a data mappaban van, nem a projekt gyokerben.
    echo.
    pause
    exit /b 1
)

start "SuliHub Flask Szerver" cmd /k "%PYTHON_EXE%" app.py
timeout /t 3 /nobreak >nul
start http://127.0.0.1:5000
echo Az alkalmazas indult: http://127.0.0.1:5000
echo A szerver ablaka nyitva marad; hiba eseten ott latszik a traceback.
timeout /t 3 /nobreak >nul
exit /b 0
