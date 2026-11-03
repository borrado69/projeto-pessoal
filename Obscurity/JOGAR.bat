@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Obscurity

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERRO] Python nao encontrado.
  echo Instale o Python 3.12 em https://www.python.org/downloads/
  echo Marque "Add python.exe to PATH" na instalacao.
  pause
  exit /b 1
)

%PY% -c "import pygame" >nul 2>nul
if errorlevel 1 (
  echo Primeira execucao: instalando o pygame...
  %PY% -m pip install pygame
  if errorlevel 1 %PY% -m pip install pygame-ce
)

%PY% rpg.py
if errorlevel 1 pause
