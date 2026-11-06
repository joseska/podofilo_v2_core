"""Pipeline de ingestión de PDFs.

Objetivo: proporcionar una API única para que todas las entradas (UI, watcher/impresora, OVE, etc.)
converjan en la misma lógica.

En esta primera iteración el pipeline se centra en:
- Normalizar rutas locales.
- Filtrar PDFs válidos.
- Evitar duplicados simples.

Importante:
- Este módulo NO depende de la UI para evitar ciclos de importación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Union


class IngestSource(str, Enum):
    """Origen de una ingestión.

    Se usa para trazabilidad (logs/metadata) y para aplicar políticas distintas en el futuro.
    """

    DRAG_DROP = "drag_drop"
    FILE_DIALOG = "file_dialog"
    STARTUP = "startup"
    SINGLE_INSTANCE = "single_instance"
    WATCHER = "watcher"
    PRINTER = "printer"
    OVE_DOWNLOAD = "ove_download"
    UNKNOWN = "unknown"


@dataclass
class IngestSkipped:
    """Elemento descartado durante la ingestión."""

    raw: str
    reason: str


@dataclass
class IngestResult:
    """Resultado de normalización/ingestión."""

    source: IngestSource
    normalized_paths: list[Path] = field(default_factory=list)
    skipped: list[IngestSkipped] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class IngestPipeline:
    """Pipeline mínimo para normalizar y preparar rutas de PDFs."""

    def normalize_local_paths(
        self,
        source: IngestSource,
        paths: Iterable[Union[str, Path]],
    ) -> IngestResult:
        """Normaliza una lista de rutas de entrada.

        - Convierte a `Path`.
        - Expande `~`.
        - Intenta `resolve()` (best-effort; no falla si el fichero no existe).
        - Filtra a PDFs existentes.
        - Elimina duplicados preservando el orden.
        """

        result = IngestResult(source=source)

        seen: set[str] = set()

        for p in (paths or []):
            raw = str(p)

            # Normalizar a Path de forma segura.
            try:
                path_obj = Path(p).expanduser()
            except Exception:
                result.skipped.append(IngestSkipped(raw=raw, reason="path_invalid"))
                continue

            # Intentar resolver (si no existe, no forzamos error).
            try:
                # strict=False evita excepciones por inexistencia en Python 3.12
                path_obj = path_obj.resolve(strict=False)
            except Exception:
                # Si no se puede resolver, seguimos con la ruta expandida.
                pass

            # Validar extensión PDF.
            if path_obj.suffix.lower() != ".pdf":
                result.skipped.append(IngestSkipped(raw=raw, reason="not_pdf"))
                continue

            # Validar existencia.
            if not path_obj.exists() or not path_obj.is_file():
                result.skipped.append(IngestSkipped(raw=raw, reason="not_found"))
                continue

            # Dedupe simple por ruta absoluta (preservando orden).
            key = str(path_obj)
            if key in seen:
                result.skipped.append(IngestSkipped(raw=raw, reason="duplicate"))
                continue
            seen.add(key)

            result.normalized_paths.append(path_obj)

        return result


def coerce_source(source: Optional[Union[str, IngestSource]]) -> IngestSource:
    """Convierte un string opcional a `IngestSource`.

    Se usa para no romper llamadas existentes: si llega un valor desconocido, cae a UNKNOWN.
    """

    if isinstance(source, IngestSource):
        return source
    if not source:
        return IngestSource.UNKNOWN

    try:
        return IngestSource(str(source))
    except Exception:
        return IngestSource.UNKNOWN
