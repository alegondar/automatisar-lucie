@echo off
rem ============================================================================
rem iniciar_bandeja.bat - Lanzador de Bandeja de Descargas (Lucie) para Windows
rem ============================================================================
chcp 65001 >nul
title Bandeja de Descargas - Lucie

cd /d "%~dp0"

echo [*] Verificando entorno Python...

set "PYTHON_CMD="

py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py -3"
    goto :python_encontrado
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :python_encontrado
)

echo.
echo ============================================================================
echo [ERROR] No se encontró Python 3 instalado o no está agregado al PATH.
echo ============================================================================
echo Para ejecutar la Bandeja de Descargas:
echo 1. Descargue el instalador oficial de Python 3.13 desde:
echo    https://www.python.org/downloads/
echo 2. Al ejecutar el instalador, ES OBLIGATORIO marcar la casilla:
echo    [X] Add python.exe to PATH (o "Agregar python.exe al PATH")
echo 3. Finalice la instalación y vuelva a hacer doble clic en este lanzador.
echo ============================================================================
echo.
pause
exit /b 1

:python_encontrado
echo [*] Intérprete detectado: %PYTHON_CMD%
echo [*] Iniciando panel web en el navegador predeterminado (http://127.0.0.1:8766)...

rem Abrir el navegador en segundo plano tras un breve instante
start "" http://127.0.0.1:8766

echo [*] Ejecutando Bandeja de Descargas... Consola de logs activa:
echo ----------------------------------------------------------------------------
%PYTHON_CMD% bandeja_descargas.py %*
set "EXIT_CODE=%errorlevel%"
echo ----------------------------------------------------------------------------
echo [*] Proceso finalizado con código %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
