@echo off
title Pantalla Extra - instalacion
echo.
echo  Instalando lo necesario para Pantalla Extra.
echo  Si Windows pregunta "Desea permitir que esta aplicacion haga cambios", responde Si.
echo.

echo [1/3] Python...
where python >nul 2>nul && (python --version) || winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements

echo.
echo [2/3] FFmpeg...
where ffmpeg >nul 2>nul && (echo FFmpeg ya esta instalado.) || winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements

echo.
echo [3/3] iTunes (version de apple.com, la que necesita Sideloadly)...
if exist "%ProgramFiles%\iTunes\iTunes.exe" (echo iTunes ya esta instalado.) else (winget install -e --id Apple.iTunes --accept-source-agreements --accept-package-agreements)

echo.
echo  Listo. Cierra esta ventana y abre una nueva antes de usar iniciar.bat.
pause
