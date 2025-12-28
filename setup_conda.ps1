# Podofilo V2 - Setup con Conda

Write-Host "=== Podofilo V2 conda deactivate - Configuración del Entorno ===" -ForegroundColor Cyan

# Verificar conda
Write-Host "`nVerificando conda..." -ForegroundColor Yellow
conda --version

# Crear environment
Write-Host "`nCreando environment 'podofilo_v2' con Python 3.14..." -ForegroundColor Yellow
conda create -n podofilo_v2 python=3.14 -y

# Activar environment
Write-Host "`nActivando environment..." -ForegroundColor Yellow
conda activate podofilo_v2

# Instalar dependencias
Write-Host "`nInstalando dependencias..." -ForegroundColor Yellow
pip install -r requirements.txt

Write-Host "`n=== Instalación Completa ===" -ForegroundColor Green
Write-Host "`nPara usar Podofilo V2:" -ForegroundColor Cyan
Write-Host "  1. conda activate podofilo_v2" -ForegroundColor White
Write-Host "  2. python main.py" -ForegroundColor White
Write-Host "`nPara desactivar el environment:" -ForegroundColor Cyan
Write-Host "  conda deactivate" -ForegroundColor White
