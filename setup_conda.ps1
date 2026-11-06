# Podofilo V2 (CORE PUBLICO) - Setup con Conda
#
# Crea/actualiza el environment conda 'podofilo_v2_core' segun
# environment.yml (solo deps core; las de la extension OVE estan en
# requirements_ove.txt y no se instalan aqui).

Write-Host "=== Podofilo V2 Core - Configuracion del Entorno ===" -ForegroundColor Cyan

# Verificar conda
Write-Host "`nVerificando conda..." -ForegroundColor Yellow
conda --version

# Crear/actualizar el environment desde environment.yml
Write-Host "`nCreando/actualizando environment 'podofilo_v2_core' (Python 3.14)..." -ForegroundColor Yellow
conda env create -f environment.yml -y
if ($LASTEXITCODE -ne 0) {
    Write-Host "El environment ya existe; actualizando deps desde requirements.txt..." -ForegroundColor Yellow
    conda activate podofilo_v2_core
    pip install -r requirements.txt
}

# Activar environment
Write-Host "`nActivando environment..." -ForegroundColor Yellow
conda activate podofilo_v2_core

# Instalar dependencias
Write-Host "`nInstalando dependencias..." -ForegroundColor Yellow
pip install -r requirements.txt

Write-Host "`n=== Instalacion Completa ===" -ForegroundColor Green
Write-Host "`nPara usar Podofilo V2 Core:" -ForegroundColor Cyan
Write-Host "  1. conda activate podofilo_v2_core" -ForegroundColor White
Write-Host "  2. python main.py" -ForegroundColor White
Write-Host "`nPara desactivar el environment:" -ForegroundColor Cyan
Write-Host "  conda deactivate" -ForegroundColor White
