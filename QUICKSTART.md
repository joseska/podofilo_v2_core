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

### 2. Instalar Navegadores (Solo para Plugin OVE)
Si vas a utilizar la integración con OVE (y tienes el plugin), necesitas los binarios de Playwright.

```powershell
playwright install chromium
```
*Si solo vas a usar el modo Open (sin OVE), puedes saltar este paso.*

## Ejecución

### Modo Open (Público)
Si no tienes la carpeta `src/extensions/ove`, la aplicación iniciará automáticamente en este modo.

```powershell
python main.py
```
*Verás un aviso en la consola indicando que la extensión OVE no se ha encontrado.*

### Modo Full (Privado)
Para activar las funciones de OVE:
1. Asegúrate de tener la carpeta `src/extensions/ove` con el código del plugin.
2. Ejecuta la aplicación de la misma forma:

```powershell
python main.py
```
*La aplicación detectará la extensión y habilitará los botones de OVE.*

## Solución de Problemas Comunes

*   **Error de DLL en PyMuPDF**: Asegúrate de `pip install --upgrade pymupdf`.
*   **No aparecen botones OVE**: Verifica que la carpeta `src/extensions/ove` existe y contiene el archivo `__init__.py`.
*   **Lentitud al inicio**: La primera vez que se ejecuta puede tardar un poco en compilar caches de Python (`__pycache__`). Las siguientes veces será instantáneo.
