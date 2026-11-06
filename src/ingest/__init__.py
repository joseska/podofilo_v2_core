"""Paquete de ingestión de documentos orientado a flujo PDF.

Este paquete centraliza la entrada de documentos desde distintas fuentes (UI, watcher/impresora,
OVE, etc.) para evitar duplicación de lógica y asegurar un comportamiento consistente.

Cuando la entrada no es PDF (por ejemplo XML o imagen), se convierte previamente a PDF temporal
para reutilizar el mismo pipeline y el mismo renderizado en la UI.

Nota: En una primera iteración se implementa un pipeline mínimo para rutas locales.
"""

from .pipeline import IngestPipeline, IngestResult, IngestSource
