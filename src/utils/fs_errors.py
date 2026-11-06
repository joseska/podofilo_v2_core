"""
Diagnóstico y robustez de errores de sistema de ficheros para PodofiloV2.

Pequeña utilidad para clasificar, describir y loguear errores de FS de forma
estructurada (tipo + errno + operación + paths) en vez de capturar con
``except Exception`` genérico que solo loguea ``e``. Incluye además dos helpers
reutilizables:

- :func:`ensure_temp_dir`  — verificar/recrear un directorio temporal antes de
  escribir en él (ataca ``FileNotFoundError [Errno 2]`` por carreras con el
  cleanup de shutdown).
- :func:`safe_rmtree`      — ``shutil.rmtree`` tolerante con handler por-fichero
  (``onexc``) que loguea cada fichero/dir bloqueado por Windows sin abortar el
  resto del árbol.

Patrón de referencia: ``translate_save_error`` en ``src/pdf/document.py``.
"""

from __future__ import annotations

import errno
import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Union

__all__ = [
    "classify_fs_error",
    "describe_fs_error",
    "log_fs_error",
    "ensure_temp_dir",
    "safe_rmtree",
]

# ---------------------------------------------------------------------------
# Clasificación
# ---------------------------------------------------------------------------

# Textos habituales en mensajes de error de FS (Windows + libs como fitz/PyMuPDF).
_PERMISSION_TEXTS = (
    "permission denied",
    "access is denied",
    "acceso denegado",
    "cannot remove file",
    "operación no permitida",
    "sharing violation",
    "being used by another process",
    "en uso por otro proceso",
    "the process cannot access the file",
)
_NOT_FOUND_TEXTS = (
    "no such file or directory",
    "the system cannot find the file",
    "el sistema no puede encontrar el archivo",
    "no se pudo encontrar",
    "no existe",
    "file not found",
)
_IN_USE_TEXTS = (
    "being used by another process",
    "en uso por otro proceso",
    "the process cannot access the file",
    "sharing violation",
    "in use",
    "en uso",
)
_DISK_FULL_TEXTS = (
    "no space left on device",
    "disk full",
    "sin espacio",
    "there is not enough space",
    "no hay suficiente espacio",
)
_CANCELLED_TEXTS = (
    "operation canceled",
    "cancelled",
    "cancelada",
    "cancelado",
    "operation aborted",
)


def classify_fs_error(exc: BaseException) -> str:
    """Clasifica un error de FS en una categoría estable.

    Devuelve uno de: ``'permission'``, ``'not_found'``, ``'in_use'``,
    ``'disk_full'``, ``'cancelled'``, ``'unknown'``.

    Usa ``errno`` cuando está disponible (subclases de :class:`OSError`) y, como
    respaldo, el texto del mensaje (algunos wrappers de libs como fitz no exponen
    ``errno``).
    """
    err = getattr(exc, "errno", None)
    if err == errno.ENOENT:
        return "not_found"
    if err in (errno.EACCES, errno.EPERM):
        return "permission"
    if err == errno.ENOSPC:
        return "disk_full"
    if err == errno.EDQUOT:
        return "disk_full"
    if err == errno.ECANCELED:
        return "cancelled"
    # En Windows la violación de sharing y "en uso por otro proceso" llega como
    # PermissionError(errno=13) — ya cubierto arriba. Aun así, comprobamos texto.

    msg = str(exc).lower()
    if any(t in msg for t in _NOT_FOUND_TEXTS):
        return "not_found"
    if any(t in msg for t in _DISK_FULL_TEXTS):
        return "disk_full"
    if any(t in msg for t in _IN_USE_TEXTS):
        return "in_use"
    if any(t in msg for t in _PERMISSION_TEXTS):
        return "permission"
    if any(t in msg for t in _CANCELLED_TEXTS):
        return "cancelled"
    return "unknown"


def describe_fs_error(
    exc: BaseException,
    operation: str,
    *,
    src: Optional[Union[str, Path]] = None,
    dst: Optional[Union[str, Path]] = None,
) -> str:
    """Construye un mensaje legible y estructurado para el log.

    Formato (plano, sin infraestructura de logging nova):
        ``[FS:<tipo>] op=<operation> | errno=<n> | src=<...> | dst=<...> | exc=<repr>``
    """
    tipo = classify_fs_error(exc)
    parts = [f"[FS:{tipo}] op={operation}"]
    err = getattr(exc, "errno", None)
    if err is not None:
        parts.append(f"errno={err}")
    if src is not None:
        parts.append(f"src={src}")
    if dst is not None:
        parts.append(f"dst={dst}")
    parts.append(f"exc={exc!r}")
    return " | ".join(parts)


def log_fs_error(
    logger: logging.Logger,
    exc: BaseException,
    operation: str,
    *,
    src: Optional[Union[str, Path]] = None,
    dst: Optional[Union[str, Path]] = None,
    level: int = logging.ERROR,
) -> None:
    """Registra un error de FS con :func:`describe_fs_error` en el nivel indicado."""
    logger.log(level, describe_fs_error(exc, operation, src=src, dst=dst))


# ---------------------------------------------------------------------------
# Helpers de robustez
# ---------------------------------------------------------------------------


def ensure_temp_dir(
    path: Union[str, Path],
    *,
    label: str,
    logger: logging.Logger,
) -> Path:
    """Verifica/recrea un directorio temporal antes de escribir en él.

    - Si existe y es escribible, lo devuelve tal cual.
    - Si no existe, intenta ``mkdir(parents=True, exist_ok=True)``.
    - Si no se puede crear o no es escribible, lanza :class:`OSError` con un
      mensaje descriptivo vía :func:`describe_fs_error`.

    No es un reintento: es garantizar que el destino existe en el instante del
    write para evitar ``FileNotFoundError`` por carreras con el cleanup de
    shutdown.
    """
    p = Path(path)
    if p.exists():
        # Ya existe: comprobamos escritura (os.access es orientativo en Windows
        # pero suficiente como sanity-check barato).
        if os.access(str(p), os.W_OK):
            return p
        # Existe pero no escribible → describimos y lanzamos.
        e = OSError(f"El directorio '{p}' existe pero no es escribible")
        raise OSError(describe_fs_error(e, f"ensure_temp_dir[{label}]", src=p)) from e

    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # No propagamos la OSError cruda: la envolvemos con contexto.
        raise OSError(
            describe_fs_error(e, f"ensure_temp_dir[{label}]", src=p)
        ) from e

    logger.info("ensure_temp_dir[%s]: recreado %s", label, p)
    return p


def safe_rmtree(
    path: Union[str, Path],
    *,
    logger: logging.Logger,
    label: str,
) -> int:
    """Borra un árbol de forma tolerante y con log por-fichero.

    Usa ``shutil.rmtree(..., onexc=...)`` (Python 3.12+). Por cada fichero/dir
    que no se pueda borrar (típico: lock de Windows por oviscapto/antivirus/Edge
    o visor abierto) loguea un ``warning`` con la ruta concreta, el tipo
    clasificado y el ``errno``, **sin abortar el resto del árbol**.

    Devuelve el número de elementos que no se pudieron borrar.
    """
    p = Path(path)
    if not p.exists():
        return 0

    errors_count = 0

    def _onexc(func, exc_path, exc_info):  # noqa: ANN001 (firma impuesta por shutil)
        nonlocal errors_count
        errors_count += 1
        exc = exc_info[1]
        try:
            tipo = classify_fs_error(exc)
        except Exception:
            tipo = "unknown"
        op_name = getattr(func, "__name__", repr(func))
        logger.warning(
            "safe_rmtree[%s]: no se pudo borrar %s (op=%s, tipo=%s, errno=%s, exc=%r)",
            label,
            exc_path,
            op_name,
            tipo,
            getattr(exc, "errno", None),
            exc,
        )
        # IMPORTANTE: no relanzar — dejar que rmtree continúe con el resto.

    try:
        shutil.rmtree(p, onexc=_onexc)
    except OSError as e:
        # Caso extremo: el propio rmtree lanza algo no capturado por onexc.
        errors_count += 1
        logger.warning(
            "safe_rmtree[%s]: fallo general sobre %s (tipo=%s, exc=%r)",
            label,
            p,
            classify_fs_error(e),
            e,
        )
    return errors_count