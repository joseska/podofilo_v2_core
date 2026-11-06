"""
Podofilo V2 - Aplicación moderna de gestión de PDFs
Punto de entrada de la aplicación
"""
import argparse
import logging
import sys
from pathlib import Path

# Única fuente de verdad para la versión de la aplicación.
# Se lee desde VERSION.txt en la raíz del repo; el instalador Inno Setup
# lee el mismo fichero (ver Instalador/podofiloV2.iss) para mantener
# versión de la app y versión del instalador siempre sincronizadas.
def _read_version_label() -> str:
    try:
        # En PyInstaller frozen, __file__ apunta a un path inexistente bajo
        # _MEIPASS; usamos sys.executable para localizar VERSION.txt que se
        # empaqueta como data en el .spec.
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            # PyInstaller 6.x onedir pone los datas en "_internal/"; en versiones
            # anteriores o onefile pueden estar en la raiz del bundle. Probamos
            # ambas ubicaciones para ser robustos.
            candidates = [
                exe_dir / "VERSION.txt",            # raiz del bundle (junto al exe)
                exe_dir / "_internal" / "VERSION.txt",  # PyInstaller 6.x onedir
            ]
        else:
            candidates = [Path(__file__).resolve().parent / "VERSION.txt"]

        for version_file in candidates:
            if version_file.exists():
                return version_file.read_text(encoding="utf-8").strip()
        return "V2_unknown"
    except Exception:
        return "V2_unknown"

APP_VERSION_LABEL = _read_version_label()


# Configuración del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# logging.basicConfig(
#     level=logging.DEBUG,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )

# Asegurar que el módulo principal de la UI emita DEBUG aunque otros modifiquen niveles
logging.getLogger("src.ui.main_window").setLevel(logging.DEBUG)
log = logging.getLogger(__name__)

def _parse_args():
    """Analiza los argumentos de la línea de comandos"""
    parser = argparse.ArgumentParser(
        description="Podofilo V2 - Gestor moderno de PDFs/XML/Imágenes"
    )
    parser.add_argument(
        "pdf",
        nargs="*",
        # Mantenemos el nombre del argumento por compatibilidad,
        # pero ahora acepta PDF, XML e imágenes (PNG/JPG/JPEG).
        help="Ruta(s) de archivos PDF/XML/imagen que se abrirán automáticamente al iniciar",
    )

    parser.add_argument(
        "--save-dialog-dir",
        dest="save_dialog_dir",
        default=None,
        help="Abre el diálogo 'Guardar como PDF' con esta carpeta preseleccionada",
    )

    parser.add_argument(
        "--ove-expediente",
        dest="ove_expediente",
        default=None,
        help="Abre el diálogo 'Subir expediente al OVE' con este nº de expediente pre-rellenado",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Activa opciones avanzadas (pestaña 'Avanzado' en Configuración) y utilidades de depuración. "
            "Por defecto esta pestaña está oculta para uso normal."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"Podofilo V2 {APP_VERSION_LABEL}",
        help="Muestra la versión de la aplicación y termina",
    )
    return parser.parse_args()

def main():
    """Punto de entrada principal"""
    # Parsear argumentos ANTES de cualquier log/efecto: flags como --version
    # o --help terminan aquí con exit 0 sin arrancar nada más.
    args = _parse_args()

    log.info("Starting Podofilo V2...")
    initial_files = [Path(p).resolve() for p in getattr(args, "pdf", [])] # Usar resolve para rutas absolutas
    # Flag de depuración: habilita la pestaña "Avanzado" en Configuración.
    debug_mode = bool(getattr(args, "debug", False))

    actions = []
    if getattr(args, "save_dialog_dir", None):
        actions.append({
            "type": "open_save_dialog",
            "dir": str(args.save_dialog_dir),
        })
    if getattr(args, "ove_expediente", None):
        actions.append({
            "type": "open_ove_upload_dialog",
            "expediente": str(args.ove_expediente),
        })

    # --- COMPROBACIÓN DE INSTANCIA ÚNICA ---
    from src.core.single_instance import send_to_instance

    payload = {
        "files": [str(p) for p in initial_files],
        "actions": actions,
        # Propagamos el modo debug a una instancia ya abierta.
        "debug": debug_mode,
    }

    if send_to_instance(payload):
        log.info("Archivos enviados a la instancia ya abierta. Cerrando esta instancia.")
        return # Salir si se enviaron con éxito

    if initial_files:
        log.info(
            "Se solicitaron %d archivo(s) para apertura inicial", len(initial_files)
        )
    
    # --- COMPROBACIÓN DE ACTUALIZACIÓN AUTOMÁTICA (1 vez al día, en segundo plano) ---
    # Se lanza antes de crear la UI para no retrasar el arranque. El resultado
    # (UpdateInfo o None) se deposita en una cola que la UI consumirá cuando
    # esté lista. El consentimiento lo da el usuario vía diálogo modal.
    import queue
    import threading
    from src.core.updater import fetch_latest, should_auto_check_today
    from src.utils.config import ConfigManager

    update_queue: "queue.Queue" = queue.Queue()

    def _startup_update_check():
        try:
            cfg = ConfigManager()
            last_check = cfg.get_last_update_check()
            if not should_auto_check_today(last_check):
                # Ya se ha comprobado hoy: no molestar.
                update_queue.put(None)
                return
            ignored = cfg.get_ignored_update_version()
            info = fetch_latest(APP_VERSION_LABEL, ignored_version=ignored)
            # Registrar el check (se hace aunque no haya update, para no repetir
            # el mismo día).
            from datetime import datetime, timezone
            cfg.set_last_update_check(datetime.now(timezone.utc).isoformat())
            update_queue.put(info)
        except Exception as exc:
            log.warning("Auto-update check falló: %r", exc)
            update_queue.put(None)

    threading.Thread(target=_startup_update_check, daemon=True).start()
    
    # Importar la UI una vez configurado el logging
    from src.ui.main_window import PodofiloApp
    
    # Crear y ejecutar la aplicación
    app = PodofiloApp(
        initial_files=initial_files,
        version_label=APP_VERSION_LABEL,
        initial_actions=actions,
        debug_mode=debug_mode,
        update_queue=update_queue,
    )
    app.run()

if __name__ == "__main__":
    main()
