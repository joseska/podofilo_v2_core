@echo off
setlocal enabledelayedexpansion

REM Podofilo V2 Core - Generador de ejecutable
REM Ejecuta este script desde la raíz del repositorio

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

echo [1/4] Activando entorno conda "podofilo_v2_core"...
call conda activate podofilo_v2_core >nul 2>&1
if errorlevel 1 (
    echo No se pudo activar el entorno "podofilo_v2_core". Asegura haber ejecutado "conda activate podofilo_v2_core" al menos una vez en esta consola.
    exit /b 1
)

echo [2/4] Limpiando construcciones previas...
if exist build rd /s /q build
if exist dist rd /s /q dist

echo [3/4] Generando ejecutable con PyInstaller...
pyinstaller --clean --noconfirm PodofiloV2.spec
if errorlevel 1 (
    echo PyInstaller reportó un error.
    exit /b 1
)

echo [4/4] Build completado.
echo Resultado: dist\PodofiloV2\PodofiloV2.exe

endlocal
exit /b 0
