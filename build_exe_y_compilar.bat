@echo off
setlocal enabledelayedexpansion

REM Podofilo V2 CORE - Generador de ejecutable + instalador + checksum
REM Ejecuta este script desde la raíz del repositorio
REM (equivalente a build_exe_y_compilar.bat de podofilo_dev, con env conda propio)

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

REM Ruta al compilador de Inno Setup (ISCC.exe)
set "ISCC_EXE=C:\Users\josem.luis\AppData\Local\Programs\Inno Setup 7\ISCC.exe"

echo [1/7] Activando entorno conda "podofilo_v2_core"...
call conda activate podofilo_v2_core >nul 2>&1
if errorlevel 1 (
    echo No se pudo activar el entorno "podofilo_v2_core". Asegura haber ejecutado "conda activate podofilo_v2_core" al menos una vez en esta consola.
    exit /b 1
)

echo [2/7] Limpiando construcciones previas...
if exist build rd /s /q build
if exist dist rd /s /q dist

echo [3/7] Generando ejecutable con PyInstaller...
pyinstaller --clean --noconfirm PodofiloV2.spec
if errorlevel 1 (
    echo PyInstaller reporto un error.
    exit /b 1
)

echo Esperando 1 segundo antes de limpiar la carpeta Instalador...
timeout /t 1 /nobreak >nul

echo [4/7] Limpiando carpeta Instalador...
if exist "Instalador\PodofiloV2.exe" del /f /q "Instalador\PodofiloV2.exe"
if exist "Instalador\_internal" rd /s /q "Instalador\_internal"

echo Esperando 2 segundos antes de copiar los archivos nuevos...
timeout /t 2 /nobreak >nul

echo [5/7] Copiando build a carpeta Instalador...
copy /y "dist\PodofiloV2\PodofiloV2.exe" "Instalador\PodofiloV2.exe" >nul
xcopy /e /i /y "dist\PodofiloV2\_internal" "Instalador\_internal" >nul
if errorlevel 1 (
    echo Error al copiar los archivos a la carpeta Instalador.
    exit /b 1
)

echo Esperando 3 segundos antes de compilar el instalador...
timeout /t 3 /nobreak >nul

echo [6/7] Compilando instalador con Inno Setup...
if not exist "%ISCC_EXE%" (
    echo No se encontro ISCC.exe en: %ISCC_EXE%
    echo Instala Inno Setup 7 o ajusta la ruta ISCC_EXE en este script.
    exit /b 1
)

REM Leemos la version desde VERSION.txt (raiz del repo) y la pasamos a ISCC
REM con /DMyAppVersion=... que es compatible con todas las versiones de ISCC,
REM evitando el uso de LoadStringFromFile del ISPP (no disponible en algunos
REM Inno Setup). tomamos la primera linea no vacia del fichero.
set "APP_VERSION="
for /f "usebackq delims=" %%V in ("VERSION.txt") do (
    if not defined APP_VERSION set "APP_VERSION=%%V"
)
if not defined APP_VERSION (
    echo No se pudo leer la version desde VERSION.txt.
    exit /b 1
)
echo Version leida desde VERSION.txt: %APP_VERSION%

REM Podofilo V2 (CORE) - Instalador Inno Setup, version leida de VERSION.txt [patron valido]
"%ISCC_EXE%" /Q /DMyAppVersion="%APP_VERSION%" "Instalador\podofiloV2.iss"
if errorlevel 1 (
    echo Inno Setup reporto un error durante la compilacion.
    exit /b 1
)

echo [7/7] Generando checksum SHA256 del instalador...
set "SETUP_EXE=Instalador\installer\PodofiloV2_Setup.exe"
set "HASH_FILE=Instalador\installer\PodofiloV2_Setup.exe.sha256"
if not exist "%SETUP_EXE%" (
    echo No se encontro el instalador generado: %SETUP_EXE%
    exit /b 1
)

REM certutil exporta un formato multilinea tipo:
REM   SHA256 hash of file.exe:
REM   <hex de 64 caracteres>
REM   CertUtil: -hashfile command completed successfully.
REM Lo limpiamos a una sola linea en formato sha256sum:
REM   <hex>  PodofiloV2_Setup.exe
REM Extraemos solo la linea de 64 hex con un bucle for /f.
REM La salida de certutil varia segun idioma (cabecera + hex + pie),
REM asi que nos saltamos la primera linea ("SHA256 hash de ...:") y
REM capturamos el primer token (que es el hex de 64 caracteres).
REM Podofilo V2 (CORE) - SHA256 con certutil basado en cert_mem: cabecera localizada + skip=1 + tokens=1
set "SHA_HEX="
for /f "skip=1 tokens=1" %%H in ('certutil -hashfile "%SETUP_EXE%" SHA256') do (
    if not defined SHA_HEX set "SHA_HEX=%%H"
)
if not defined SHA_HEX (
    echo No se pudo extraer el hash SHA256 del instalador.
    exit /b 1
)

REM Escribimos el .sha256 en formato sha256sum (hex + 2 espacios + nombre).
REM Esto es lo que esperan los tests verify_sha256 y el updater.
> "%HASH_FILE%" echo !SHA_HEX!  PodofiloV2_Setup.exe

if not exist "%HASH_FILE%" (
    echo No se pudo escribir el fichero de checksum: %HASH_FILE%
    exit /b 1
)

echo Build completado.
echo Ejecutable : Instalador\PodofiloV2.exe
echo Instalador: Instalador\installer\PodofiloV2_Setup.exe
echo Checksum  : Instalador\installer\PodofiloV2_Setup.exe.sha256

endlocal
exit /b 0
