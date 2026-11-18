@echo off
title Pantalla Extra
cd /d "%~dp0"
python pantalla.py %*
if errorlevel 1 pause
