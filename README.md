# Podofilo V2 - Gestor de PDFs para Extranjería (Open Core)

## Descripción
Podofilo V2 es una modernización completa de la aplicación original, reconstruida con Python 3.12+ (compatible con 3.14) y librerías modernas. Diseñada como una herramienta de "núcleo abierto" (Open Core), permite la gestión avanzada de documentación de expedientes de extranjería, con capacidad de extenderse mediante plugins para integraciones específicas (como el sistema OVE).

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
- **Vigilancia**: Importación automática desde carpeta (compatible con "Imprimir a PDF").

### Integración OVE (Solo con Plugin)
- **Descarga Masiva**: Obtención de expedientes completos (Ctrl+O).
- **Subida Inteligente**: Detección de número de expediente y subida directa (Ctrl+S).
- **Firmas**: Soporte para tipos de firma y conexión con portafirmas.
- **Auto-conexión**: Gestión de credenciales seguras y reconexión automática.

## Instalación y Uso
Ver [QUICKSTART.md](QUICKSTART.md) para instrucciones detalladas de instalación.

## Estructura del Proyecto
```
podofilo_v2/
├── main.py                    # Punto de entrada
├── requirements.txt           # Dependencias
├── src/
│   ├── core/                  # Lógica central y Extension Loader
│   ├── ui/                    # Interfaz de usuario
│   ├── pdf/                   # Motor de procesamiento PDF
│   └── extensions/            # Carpeta de Plugins
│       └── ove/               # (Privado) Código de integración OVE
└── ...
```

## Notas de Versión Recientes
### V2.OpenCore (Diciembre 2025)
- **Separación de Código**: Aislamiento total del código OVE en extensión.
- **Carga Dinámica**: La UI se adapta a la presencia/ausencia de extensiones.

### V2.Optimización (Diciembre 2025)
- **Rendimiento**: Zoom instantáneo, startup ultrarrápido (<3s).
- **Estabilidad**: Solución a problemas de enfoque y visualización.
