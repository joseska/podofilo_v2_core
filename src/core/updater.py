"""
Updater - Comprobación y aplicación de actualizaciones de PodofiloV2 (core).

Origen de las releases públicas del propio repositorio de este proyecto,
`joseska/podofilo_v2_core`. Al ser un repo público, NO requiere token
ni autenticación; los assets se sirven via redirección a
`objects.githubusercontent.com` (sigue redirects por defecto en httpx).

Flujo:
  1. `fetch_latest(local_version)` → consulta `releases/latest`, compara tag
     con la versión local y devuelve `UpdateInfo` si hay novedad.
  2. La UI decide (con consentimiento) si descarga + instala.
  3. `download_asset` baja el setup y su hash a `%TEMP%`.
  4. `verify_sha256` valida el setup contra el hash.
  5. `launch_and_exit` lanza el instalador Inno Setup en modo silencioso y
     cierra Python de forma abrupta (`os._exit`) para liberar el lock del exe
     antes de que Inno intente borrar la carpeta `{app}`.

Convenciones:
  - El asset del setup se llama `PodofiloV2_Setup.exe` (mismo nombre que
    `OutputBaseFilename` del .iss).
  - El hash se llama `PodofiloV2_Setup.exe.sha256` (formato `sha256sum`:
    `<hex>  <filename>` o solo `<hex>`).
  - El tag de la release DEBE ser la versión (`APP_VERSION_LABEL`, formato
    semver "M.m.p", prefijo `v` opcional). La comparación es por orden de
    componentes numéricos; el formato histórico `V2_*` no está soportado
    (cae al fallback de desigualdad de strings).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

import httpx

log = logging.getLogger(__name__)

# --- Configuración del origen de releases (repo público de este proyecto) -----
GITHUB_OWNER = "joseska"
GITHUB_REPO = "podofilo_v2_core"

SETUP_ASSET_NAME = "PodofiloV2_Setup.exe"
HASH_ASSET_NAME = f"{SETUP_ASSET_NAME}.sha256"

LATEST_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
# Plantilla para URL de descarga directa del asset por tag + nombre.
DOWNLOAD_URL_TEMPLATE = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
    "/releases/download/{tag}/{asset_name}"
)

USER_AGENT = "PodofiloV2-updater"
HTTP_TIMEOUT_SECONDS = 10.0
DOWNLOAD_TIMEOUT_SECONDS = 60.0

# Tamaño de bloque para streaming + hashing.
_CHUNK = 64 * 1024

# Patrón SHA256: 64 hex. Acepta "hex  filename" o "hex" a secas.
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")

# Transport IPv4-forzado para reintento de descargas.
#
# GitHub releases redirigen a objects.githubusercontent.com (bucket de AWS S3),
# cuyas IPs IPv6 no son alcanzables desde algunas redes con IPv6 mal configurado.
# Windows aplica Happy Eyeballs (RFC 8305) y prefiere IPv6 intentandolo primero:
# si IPv6 no responde, el servidor S3 puede cerrar la conexion sin enviar nada
# -> httpx levanta RemoteProtocolError('Server disconnected without sending a
# response.').  El API de GitHub (api.github.com) en cambio funciona por IPv6
# sin problema, por lo que fetch_latest() completa exitosamente y solo falla
# en download_asset().  Forzar IPv4 (local_address='0.0.0.0') evita probar el
# destino IPv6 y resuelve el caso Usamos como reintento, no como default,
# para no perjudicar a redes sanas que prefieran IPv6.
_IPV4_TRANSPORT = httpx.HTTPTransport(local_address="0.0.0.0")


# --- Modelos ------------------------------------------------------------------
@dataclass
class UpdateInfo:
    """Información sobre una actualización disponible."""

    tag: str                     # tag_name remoto
    setup_url: str               # URL de descarga del setup .exe
    hash_url: str               # URL de descarga del .sha256
    setup_size: int             # Tamaño del setup en bytes (0 si se desconoce)
    html_url: str               # URL de la release en GitHub (para "ver más")
    body: str                   # Changelog (cuerpo Markdown de la release)


# --- Limpieza de descargas previas en %TEMP% ----------------------------------
def _update_staging_dir() -> Path:
    """Carpeta donde se descargan setup + hash antes de instalar."""
    return Path(tempfile.gettempdir()) / "PodofiloV2_update"


def clean_staging_dir() -> None:
    """Borra la carpeta de staging de update en %TEMP%.

    Se llama antes de comenzar una nueva descarga para no acumular
    instaladores de intentos anteriores (y versiones viejas).
    """
    staging = _update_staging_dir()
    try:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.warning("No se pudo limpiar la carpeta de staging %s: %r", staging, exc)
        # Mejor continuar: si no podemos limpiar, al menos asegurar que existe.
        try:
            staging.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


# --- API GitHub ----------------------------------------------------------------
def _gh_get(url: str, *, accept: str) -> Optional[dict]:
    """GET a la API de GitHub con headers estándar. Devuelve JSON o None."""
    try:
        # Nota: las URLs de download de assets redirigen a S3-like; httpx sigue
        # redirects por defecto en `follow_redirects=True`. Para la API pura
        # no hace falta, lo activamos anyway para ser robustos.
        with httpx.Client(
            timeout=HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={
                "Accept": accept,
                "User-Agent": USER_AGENT,
            },
        ) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                log.info("GitHub %s -> HTTP %d", url, resp.status_code)
                return None
            return resp.json()
    except Exception as exc:
        log.warning("Error consultando %s: %r", url, exc)
        return None


def get_latest_release() -> Optional[dict]:
    """Devuelve el JSON de la release `latest` o None ante cualquier error."""
    return _gh_get(LATEST_URL, accept="application/vnd.github+json")


def parse_assets(release: dict) -> Optional[tuple[dict, dict]]:
    """Extrae (setup_asset, hash_asset) de la release.

    Devuelve None si faltan assets o no hay release.
    """
    if not release:
        return None
    assets = release.get("assets") or []
    setup_asset = None
    hash_asset = None
    for asset in assets:
        name = asset.get("name", "")
        if name == SETUP_ASSET_NAME:
            setup_asset = asset
        elif name == HASH_ASSET_NAME:
            hash_asset = asset
    if setup_asset is None or hash_asset is None:
        log.info(
            "Release %s sin assets esperados (setup=%s, hash=%s)",
            release.get("tag_name", "?"),
            bool(setup_asset),
            bool(hash_asset),
        )
        return None
    return setup_asset, hash_asset


def _parse_version(s: str) -> Optional[tuple[int, ...]]:
    """Parsea una versión semver "M.m.p" (prefijo `v`/`V` opcional) a tupla de ints.

    Solo se soporta el formato nuevo con puntos. El formato histórico
    `V2_12_08_2026_2` y sufijos tipo "1.0.5-beta" devuelven None.
    """
    clean = (s or "").strip()
    if clean[:1] in ("v", "V"):
        clean = clean[1:]
    parts = clean.split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def compare_versions(local: str, remote_tag: str) -> bool:
    """Devuelve True si `remote_tag` es una versión MÁS NUEVA que `local`.

    Se comparan los componentes numéricos de ambas versiones (semver con
    puntos). Si una versión no parsea (p. ej. `V2_unknown` local), se usa
    desigualdad de strings como fallback para no bloquear la actualización.
    """
    local_clean = (local or "").strip()
    remote_clean = (remote_tag or "").strip()
    if not local_clean or not remote_clean:
        return False

    local_v = _parse_version(local_clean)
    remote_v = _parse_version(remote_clean)
    if local_v is not None and remote_v is not None:
        return remote_v > local_v
    # Fallback: alguna versión no parseable (comportamiento histórico).
    return local_clean != remote_clean


def fetch_latest(local_version: str, ignored_version: str = "") -> Optional[UpdateInfo]:
    """Orquestación de comprobación de actualizaciones.

    Devuelve `UpdateInfo` si hay una versión más nueva que la local (y
    distinta de la versión ignorada), o None en caso contrario.
    """
    try:
        clean_staging_dir()
    except Exception:
        # Limpiar nunca debe romper el check de update.
        pass

    release = get_latest_release()
    if not release:
        return None

    remote_tag = release.get("tag_name", "").strip()
    if not remote_tag:
        return None

    if not compare_versions(local_version, remote_tag):
        # Misma versión: actualizado.
        return None

    if ignored_version and ignored_version.strip() == remote_tag:
        # El usuario marcó "Ignorar esta versión".
        return None

    assets = parse_assets(release)
    if assets is None:
        return None
    setup_asset, hash_asset = assets

    return UpdateInfo(
        tag=remote_tag,
        setup_url=setup_asset.get("browser_download_url", "")
        or _download_url(remote_tag, SETUP_ASSET_NAME),
        hash_url=hash_asset.get("browser_download_url", "")
        or _download_url(remote_tag, HASH_ASSET_NAME),
        setup_size=int(setup_asset.get("size", 0) or 0),
        html_url=release.get("html_url", ""),
        body=release.get("body", "") or "",
    )


def _download_url(tag: str, asset_name: str) -> str:
    """Construye la URL de descarga directa (fallback sin API)."""
    return DOWNLOAD_URL_TEMPLATE.format(tag=tag, asset_name=asset_name)


# --- Descarga + verificación ---------------------------------------------------
def _stream_download_once(
    url: str,
    dest: Path,
    progress_cb: Optional[Callable[[int, int], None]],
    transport: Optional[httpx.BaseTransport],
) -> bool:
    """Un único intento de descarga por streaming.

    `transport=None` usa el transporte por defecto de httpx (Happy Eyeballs
    del SO).  Pasar `_IPV4_TRANSPORT` fuerza IPv4 (ver comentario en la
    definición de la constante).
    """
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # `httpx.stream` (función módulo) no acepta `transport` en algunas
        # versiones (p.ej. 0.28.x), por eso construimos el Client explícito
        # pasando el transport y usamos `client.stream(...)`.
        with httpx.Client(
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        ) as client, client.stream("GET", url) as resp:
            if resp.status_code != 200:
                log.warning("Download %s -> HTTP %d", url, resp.status_code)
                return False
            total = int(resp.headers.get("content-length", "0") or 0)
            downloaded = 0
            tmp_dest = dest.with_suffix(dest.suffix + ".part")
            with open(tmp_dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None:
                        try:
                            progress_cb(downloaded, total)
                        except Exception:
                            # La UI nunca debe romper la descarga.
                            pass
            # Renombrar .part -> dest atómico (en la misma carpeta).
            tmp_dest.replace(dest)
            return True
    except Exception as exc:
        log.warning("Error descargando %s: %r", url, exc)
        return False


def download_asset(
    url: str,
    dest: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Descarga `url` a `dest` por streaming. Opcional callback(downloaded, total).

    Hace un primer intento con el transporte por defecto (Happy Eyeballs del
    SO, que prefiere IPv6 si está disponible).  Si falla —típicamente
    `RemoteProtocolError('Server disconnected...')` cuando IPv6 hacia el
    bucket de GitHub (`objects.githubusercontent.com`) está mal en la red del
    usuario— reintenta forzando IPv4 (`_IPV4_TRANSPORT`).

    Devuelve True si algún intento completa OK, False si ambos fallan.
    """
    if _stream_download_once(url, dest, progress_cb, transport=None):
        return True
    log.info(
        "Descarga %s fallida con red por defecto; reintentando forzando IPv4.",
        url,
    )
    return _stream_download_once(url, dest, progress_cb, transport=_IPV4_TRANSPORT)


def verify_sha256(setup_path: Path, hash_path: Path) -> bool:
    """Verifica SHA256 del setup contra el hash descargado.

    Acepta formatos:
      - `<hex>` (hex solo)
      - `<hex>  <filename>` (estilo sha256sum)
      - `<hex> <filename>`
    """
    try:
        if not setup_path.exists() or not hash_path.exists():
            return False
        hash_text = hash_path.read_text(encoding="utf-8", errors="ignore")
        m = _SHA256_RE.search(hash_text)
        if not m:
            log.warning("No se encontró hash SHA256 válido en %s", hash_path)
            return False
        expected = m.group(1).lower()

        h = hashlib.sha256()
        with open(setup_path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                h.update(chunk)
        actual = h.hexdigest().lower()

        if actual != expected:
            log.warning("Hash no coincidente: esperado=%s actual=%s", expected, actual)
            return False
        return True
    except Exception as exc:
        log.warning("Error verificando SHA256: %r", exc)
        return False


# --- Lanzamiento del instalador ------------------------------------------------
def launch_and_exit(setup_path: Path) -> None:
    """Lanza el instalador Inno Setup en modo silencioso y CIERRA la app.

    El cierre debe ser abrupto (`os._exit`) para garantizar que el .exe de
    Podofilo se libere antes de que Inno Setup intente borrar la carpeta
    `{app}` (comportamiento del .iss actual: `CurStepChanged -> ssInstall
    -> DelTree`). Si usáramos `sys.exit` se ejecutarían handlers de
    tkinter/atexit que podrían demorar el cierre.

    Notas:
      - `/SILENT`     : muestra la ventana de progreso (sin wizard); asi el
                        usuario VE la instalacion pero no necesita tocar nada.
      - `/NORESTART`  : no reiniciar Windows tras instalar.
      - `/NOCANCEL`   : el usuario no puede cancelar a mitad.
      - `/SP-`        : deshabilita la página de bienvenida.

    IMPORTANTE: usamos `/SILENT` (no `/VERYSILENT`) para que se vea la barra
    de progreso. Para que la app se reabra sola tras instalar, al usar modo
    silencioso NO debe estar el flag `skipifsilent` en la sección [Run] del
    .iss (ver Instalador/podofiloV2.iss).
    """
    args = [
        str(setup_path),
        "/SILENT",
        "/NORESTART",
        "/NOCANCEL",
        "/SP-",
    ]
    log.info("Lanzando instalador: %s", " ".join(args))
    try:
        # close_fds=True para no heredar handles de la app.
        subprocess.Popen(args, close_fds=True)
    except Exception as exc:
        log.error("No se pudo lanzar el instalador %s: %r", setup_path, exc)
        # Re-lanzar: la UI ya está comprometida si llegamos aquí.
        raise

    # Pequeña espera para que el setup arranque antes de que el proceso
    # de Python desaparezca. 200ms suele ser suficiente.
    import time

    time.sleep(0.2)
    os._exit(0)


def should_auto_check_today(last_check_iso: str) -> bool:
    """True si hoy aún no se ha hecho el check automático.

    Compara solo YYYY-MM-DD (UTC) para tolerar desviaciones horarias
    pequeñas y evitar checks repetidos durante el mismo día.
    """
    try:
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not last_check_iso:
            return True
        # last_check_iso viene como ISO 8601; basta con comparar la fecha.
        return last_check_iso[:10] != today
    except Exception:
        # Ante cualquier duda, permitir el check (no rompe nada).
        return True