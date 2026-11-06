# Podofilo V2 - Guía de Inicio Rápido

## Requisitos Previos
- **Windows 10/11**
- **Python 3.12+** (Probado y optimizado para 3.14)
- **Dependencias del sistema**: Visual C++ Redistributable (habitual en Windows)

## Instalación

### 1. Clonar y Preparar Entorno
Se recomienda usar **Conda** para gestionar el entorno.

```powershell
# Opción A: script automático (crea el env 'podofilo_v2_core' segun environment.yml)
./setup_conda.ps1

# Opción B: manual
conda create -n podofilo_v2_core python=3.14 -y
conda activate podofilo_v2_core

# Instalar dependencias
pip install -r requirements.txt
```


## Ejecución

### Modo Open (Público)
```powershell
python main.py            # Interfaz gráfica
python main.py --version  # Imprime la versión de VERSION.txt (sin abrir ventana)
python main.py --debug    # Arranque con logging detallado
```

La app comprueba 1 vez al día si hay una release nueva en
`github.com/joseska/podofilo_v2_core/releases`; también puedes comprobarlo
manualmente desde **Configuración → Comprobar actualizaciones**.

### Modo Full (con extensión OVE, privado)
Si dispones del código de la extensión privada:

```powershell
pip install -r requirements_ove.txt
xcopy /E /I "\ruta\a\src\extensions\ove" src\extensions\ove
python main.py
```

Sin esos pasos la app funciona igualmente en **Open Core mode**
(sin botón OVE, sin conexiones externas).

## Pruebas
```powershell
conda activate podofilo_v2_core
python -m unittest discover -s tests -v
```


## Solución de Problemas Comunes

*   **Error de DLL en PyMuPDF**: Asegúrate de `pip install --upgrade pymupdf`.
*   **Lentitud al inicio**: La primera vez que se ejecuta puede tardar un poco en compilar caches de Python (`__pycache__`). Las siguientes veces será instantáneo.
