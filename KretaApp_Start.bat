@echo off
title KRETA Alkalmazas Inditasa
chcp 65001 >nul

:: Navigálás a projekt mappájába
cd /d "C:\ReiTam\AI\Gemini\Kreta"


echo ===================================================
echo   KRÉTA Adatbázis Áttekintő Indítása...
echo ===================================================
echo.

:: Flask szerver indítása egy külön háttérablakban
start "KRETA Flask Szerver" python app.py

:: Rövid várakozás (2 másodperc), amíg a Flask elindul
timeout /t 2 /nobreak >nul

:: Weboldal megnyitása az alapértelmezett böngészőben
start http://127.0.0.1:5000

echo Az alkalmazás sikeresen elindult!
echo Ez az ablak automatikusan bezárul...
timeout /t 2 /nobreak >nul
exit