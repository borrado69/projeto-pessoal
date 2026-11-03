@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Obscurity - Criar EXE
echo ==================================================
echo   OBSCURITY - criando o executavel (Obscurity.exe)
echo ==================================================

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo.
  echo [ERRO] Python nao encontrado.
  echo Instale o Python 3.12 em https://www.python.org/downloads/
  echo Marque a opcao "Add python.exe to PATH" na instalacao e rode este arquivo de novo.
  pause
  exit /b 1
)
if not exist rpg.py (
  echo [ERRO] rpg.py nao esta nesta pasta.
  pause
  exit /b 1
)

echo.
echo [1/3] Instalando dependencias: pygame e pyinstaller...
%PY% -m pip install --upgrade pip >nul 2>nul
%PY% -m pip install pygame pyinstaller
if errorlevel 1 (
  echo pygame falhou, tentando pygame-ce...
  %PY% -m pip install pygame-ce pyinstaller
  if errorlevel 1 (
    echo [ERRO] Nao foi possivel instalar as dependencias. Use o Python 3.12.
    pause
    exit /b 1
  )
)

echo.
echo [2/3] Gerando o Obscurity.exe - pode levar alguns minutos...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name Obscurity rpg.py
if errorlevel 1 (
  echo [ERRO] Falha ao gerar o exe.
  pause
  exit /b 1
)

echo.
echo [3/3] Finalizando...
copy /y "dist\Obscurity.exe" "Obscurity.exe" >nul

echo.
echo ==================================================
echo   PRONTO!  Obscurity.exe foi criado nesta pasta.
echo   Saves e configuracoes ficam ao lado do .exe.
echo ==================================================
pause
