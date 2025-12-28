# Podofilo V2 - Build Script

Write-Host "Building Podofilo V2..." -ForegroundColor Green

# Check Python version
$pythonVersion = python --version 2>&1
Write-Host "Python version: $pythonVersion"

# Install dependencies
Write-Host "`nInstalling dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install dependencies!" -ForegroundColor Red
    exit 1
}

Write-Host "`nDependencies installed successfully!" -ForegroundColor Green
Write-Host "`nTo run the application:" -ForegroundColor Cyan
Write-Host "  python main.py" -ForegroundColor White
