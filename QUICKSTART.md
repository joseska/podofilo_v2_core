# Podofilo V2 - Guía de Inicio Rápido

## Requisitos Previos
- **Windows 10/11**
- **Python 3.12+** (Probado y optimizado para 3.14)
- **Dependencias del sistema**: Visual C++ Redistributable (habitual en Windows)

## Instalación

### 1. Clonar y Preparar Entorno
Se recomienda usar **Conda** para gestionar el entorno.

```powershell
# Crear entorno (ejemplo con Python 3.14)
conda create -n podofilo_v2 python=3.14 -y
conda activate podofilo_v2

# Instalar dependencias
pip install -r requirements.txt
```


## Ejecución

### Modo Open (Público)
```powershell
python main.py
```


## Solución de Problemas Comunes

*   **Error de DLL en PyMuPDF**: Asegúrate de `pip install --upgrade pymupdf`.
*   **Lentitud al inicio**: La primera vez que se ejecuta puede tardar un poco en compilar caches de Python (`__pycache__`). Las siguientes veces será instantáneo.
