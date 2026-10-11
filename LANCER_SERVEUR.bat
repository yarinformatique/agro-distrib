@echo off
title Agro-Distrib B2B - Serveur & Tunnel Permanent
cd /d "%~dp0"
echo ========================================================
echo   DEMARRAGE DE SAAS AGRO-DISTRIB B2B (MULTI-TENANT)
echo ========================================================
echo.

:: Lancer le serveur Django
echo [1/2] Lancement du serveur Django sur 0.0.0.0:8000...
start /b "" python manage.py runserver 0.0.0.0:8000

:: Attendre 3 secondes que Django soit prêt
timeout /t 3 /nobreak >nul

:: Lancer le tunnel Cloudflare
echo [2/2] Lancement du Tunnel Cloudflare en arriere-plan...
start /b "" cloudflared.exe tunnel --url http://127.0.0.1:8000

echo.
echo ========================================================
echo   APPLICATION EN LIGNE ET ACCESSIBLE PARTOUT DANS LE MONDE
echo ========================================================
echo   - Local : http://127.0.0.1:8000/
echo   - Comptes :
echo       * Superadmin : superadmin / admin123
echo       * Promotrice : demo / 123
echo       * Livreur    : livreur_demo / 123
echo ========================================================
echo.
echo Gardez cette fenetre ouverte ou reduite dans la barre des taches.
pause
