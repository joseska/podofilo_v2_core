# Podofilo V2 - Gestor de PDFs para Extranjería (Open Core)

## Descripción
Podofilo V2 es una modernización completa de la aplicación original, reconstruida con Python 3.12+ (compatible con 3.14) y librerías modernas. Diseñada como una herramienta de "núcleo abierto" (Open Core), permite la gestión avanzada de documentación de expedientes de extranjería, con capacidad de extenderse mediante plugins para integraciones específicas (como el sistema OVE).

![Podofilo V2](resources/image1.png)

## Arquitectura Open Core
Esta versión introduce una arquitectura modular que separa el núcleo de la aplicación de las integraciones propietarias:

*   **Modo Open (Público):** Funciona como un potente gestor y organizador de PDFs sin dependencias externas. Ideal para uso general.
*   **Modo Full (Privado):** Al añadir el plugin `src/extensions/ove`, se activan las funcionalidades de conexión con la Sede Electrónica (OVE), descarga y subida de expedientes.

## Stack Tecnológico

| Componente | Tecnología | Descripción |
|------------|------------|-------------|
| **UI** | CustomTkinter + tkinterDnD2 | Framework moderno con soporte drag-drop |
| **PDF** | PyMuPDF (fitz) | Manipulación de PDFs sin DLLs externas |
| **Imágenes** | Pillow + Cache LRU | Procesamiento de thumbnails de alto rendimiento |
| **Plugin OVE** | Playwright + httpx | Automatización robusta y asíncrona (Solo modo Full) |

## Funcionalidades Principales

### Gestión de PDFs (Núcleo)
- **Grid Virtualizado**: Rendimiento fluido con cientos de páginas.
- **Zoom Instantáneo**: Sistema de caché multi-nivel con precarga inteligente.
- **Edición**: Rotar, duplicar, insertar blancos, eliminar.
- **Organización**: Sistema de Cajas (Staging Area) y Secciones.
- **Efecto Abanico**: Visualización de arrastre estilo V1.
- **Split Visual**: Dividir documentos desde el editor o mediante atajos.
- **Numeración**: Estampado de números de página configurable.
- **Índice automático**: Generación de página de índice de expediente (`generate_index_pdf`).
- **Vigilancia**: Importación automática desde carpeta (compatible con "Imprimir a PDF").
- **Instancia única**: Abrir PDFs desde el explorador se envía a la app ya abierta.
- **Actualizador integrado**: Comprobación diaria de releases con verificación `sha256`.

### Integración OVE (Solo con Plugin)
- **Descarga Masiva**: Obtención de expedientes completos (Ctrl+O).
- **Subida Inteligente**: Detección de número de expediente y subida directa (Ctrl+S).
- **Firmas**: Soporte para tipos de firma y conexión con portafirmas.
- **Auto-conexión**: Gestión de credenciales seguras y reconexión automática.

## Instalación y Uso
Ver [QUICKSTART.md](QUICKSTART.md) para instrucciones detalladas de instalación.

Para mantener el core al día con los cambios de `podofilo_dev`, ver
[docs/SYNC.md](docs/SYNC.md).

## Estructura del Proyecto
```
podofilo_v2_core/
├── main.py                    # Punto de entrada (flags --version/--debug)
├── VERSION.txt                # Fuente única de la versión (semver)
├── requirements.txt           # Dependencias del core
├── requirements_ove.txt       # Dependencias SOLO de la extensión OVE
├── Instalador/podofiloV2.iss  # Instalador Inno Setup (AppId propio del core)
├── docs/SYNC.md               # Política de sincronización dev -> core
├── tests/                     # Suite pública (unittest)
├── src/
│   ├── core/                  # Lógica central, updater, watcher y Extension Loader
│   ├── ui/                    # Interfaz de usuario
│   ├── pdf/                   # Motor de procesamiento PDF (+ generación de índice)
│   ├── ingest/                # Pipeline unificado de importación
│   └── extensions/            # Carpeta de Plugins
│       └── ove/               # (Privado) Código de integración OVE
└── resources/                 # Iconos, tema, .ico
```

## Versiones y actualizaciones

- La versión del programa vive en `VERSION.txt` (los builds actuales empiezan en `1.0.0`).
- `python main.py --version` la imprime sin abrir ninguna ventana.
- **Actualizaciones automáticas**: al abrir, la app comprueba 1 vez al día las
  releases **de este repositorio** (`joseska/podofilo_v2_core`) y avisa si hay una
  versión mayor. Desde *Configuración* se puede "Comprobar ahora"; aceptar una
  descarga descarga `PodofiloV2_Setup.exe` + verifica su `sha256` y lanza el instalador
  en modo silencioso, relanzando la app al terminar.
- Las actualizaciones se pueden ignorar por versión ("Ignorar esta versión").
- Las releases NO contienen la extensión OVE; solo el núcleo.

## Instalar la extensión OVE opcional (modo Full, privado)

Sal que la versión pública no trae la extensión. Si dispones del código privado:

1. `conda activate podofilo_v2_core` (o tu entorno)
2. `pip install -r requirements_ove.txt`
3. Copia el directorio `src/extensions/ove` (mantenieado el nombre, incluidos
   `manager.py`, `service.py` y la subcarpeta `ui/`) junto a `src/extensions/`.
4. Reinicia la app; el cargador detecta el plugin y los menús OVE se activan
   (Ctrl+O descarga, Ctrl+S subir, conexión al portafirmas).

Sin esos pasos la app arranca igualmente en **Open Core mode** (ver logs:
`"Extension OVE not found. Running in Open Core mode."`) y no se empaqueta ni
instala ninguna dependencia de la extensión.

### Línea de pruebas
```
python -m unittest discover -s tests -v
```

## Notas de Versión Recientes
### V2 Core 1.0.0 (Noviembre 2026) — Sincronización con podofilo_dev
- **Re-carga del núcleo**: la carpeta `src/` del core (menos `src/extensions/ove`) se
  sustituye por la de `podofilo_dev` (la build con OVE, que es un superconjunto),
  conservando todo el mecanismo open-core (guards `if self.extensions:`).
- **Nuevas funcionalidades core**: pipeline unificado de importación (`src/ingest`),
  índice de expediente (`src/pdf/index_page.py`), robustez de ficheros temporales
  (`src/utils/fs_errors.py`), tooltips, y soporte de instancias externas
  (`--save-dialog-dir`, `--debug`, dict actions del protocolo single-instance).
- **Actualizador propio**: las releases del core viven en este repositorio y el
  updater consulta `joseska/podofilo_v2_core/releases/latest`.
- **Versionado semver**: `VERSION.txt` (`1.0.0`), flag `--version`, integración con
  el instalador Inno Setup (AppId `PodofiloV2Core` distinto del instalador con OVE).
- **Dependencias limpias**: el build público ya no incluye playwright, keyring,
  pypac, lxml, greenlet ni dukpy (ver `requirements_ove.txt`).
- **Tests públicos**: primera suite pública en `tests/` (unittest), con regresiones
  del updater, del pipeline de ingest y de la conversión imagen/XML → PDF.

### V2 (14 de Enero 2026)
- **Mejoras de UX en Menús**: Deshabilitación dinámica de las opciones "Subir al OVE" y "Modo Corte" en el menú contextual y atajos de teclado cuando no hay documentos cargados, mejorando la coherencia de la interfaz.
- **Actualización de Versión**: Sincronización de etiquetas internas para reflejar la versión estable actual.

### V2.UI/UX & Fixes (Enero 2026)
- **Mejora Visual de Secciones**: Implementación de encabezados con efecto de cristal (glassmorphism) e identificadores laterales cromatizados para facilitar la distinción entre documentos.
- **Corrección de Estado (Undo)**: Se ha corregido el comportamiento del sistema de deshacer (`Ctrl+Z`) para evitar cambios de vista accidentales tras operaciones de corte o división.
- **Refactorización Core**: Limpieza de dependencias y optimización del cargador de extensiones para un arranque más limpio en entornos sin el plugin OVE.

### V2.OpenCore (Diciembre 2025)
- **Separación de Código**: Aislamiento total del código OVE en su propia extensión.
- **Carga Dinámica**: Adaptación automática de la interfaz según los componentes disponibles.

### V2.Optimización (Diciembre 2025)
- **Rendimiento**: Implementación de zoom instantáneo y reducción del tiempo de inicio a menos de 3 segundos.
- **Estabilidad**: Corrección de fallos de enfoque y parpadeos en el grid virtualizado.

## Licencia
Este proyecto está licenciado bajo la **GNU General Public License v3.0**.
Consulte el archivo [LICENSE](LICENSE) para ver el texto completo de la licencia.