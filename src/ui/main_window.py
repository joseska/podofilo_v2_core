"""

Main Window - CustomTkinter based UI

"""

from __future__ import annotations



import logging

import customtkinter as ctk

import tkinter as tk

from tkinter import filedialog, messagebox, Menu

from tkinterdnd2 import TkinterDnD, DND_FILES

from typing import Dict, List, Optional, Callable

from pathlib import Path

from PIL import Image, ImageTk

import threading

import os

import contextlib

import shutil

import tempfile

import sys

import fitz  # PyMuPDF

import copy

from collections import Counter



from src.ui.pdf_viewer import PdfViewer

from src.ui.virtual_grid import VirtualGrid

from src.ui.sidebar import SectionSidebar

from src.ui.save_dialog import SaveDialog

from src.ui.dialogs import CenteredInputDialog, SectionNamesEditorDialog, ProgressDialog

from src.ui.page_editor import PageEditorWindow

from src.ui.theme import get_theme, get_button_style, get_menu_icon

from src.ui.tooltip import ToolTip

from src.pdf.structure import SectionManager, Section, LocalDocumentBox, BoxState, RemoteDocumentBox, PageReference

from src.pdf.document import PdfDocument

from src.pdf.numbering import PdfNumbering

from src.utils.config import ConfigManager
from src.utils.fs_errors import log_fs_error, ensure_temp_dir, safe_rmtree

from src.ingest.pipeline import IngestPipeline, IngestSource

from src.ingest.xml_to_pdf import convert_xml_file_to_pdf

from src.ingest.image_to_pdf import convert_image_file_to_pdf

from src.core.extension_loader import load_ove_extension

from src.core.watcher import WatcherManager

from src.core.single_instance import InstanceServer

import src.analysis.analisis as analisis



log = logging.getLogger(__name__)



# Extensiones de imagen soportadas para conversión previa a PDF.

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# Archivos locales no-PDF que convertimos a PDF para mantener el flujo interno homogéneo.

SUPPORTED_CONVERTIBLE_EXTENSIONS = {".xml", *SUPPORTED_IMAGE_EXTENSIONS}



class DnDApp(ctk.CTk, TkinterDnD.DnDWrapper):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.TkdndVersion = TkinterDnD._require(self)



class PodofiloApp:

    """Main application window"""

    

    def __init__(

        self,

        initial_files: Optional[List[Path]] = None,

        version_label: str = "",

        initial_actions: Optional[list] = None,

        debug_mode: bool = False,

        update_queue: Optional["queue.Queue"] = None,

    ):

        """Initialize application"""

        log.info("Iniciando Podofilo V2...")



        # Modo debug: controla si exponemos opciones avanzadas (pestaña "Avanzado" en Configuración).

        self.debug_mode = bool(debug_mode)

        

        # Initialize Config

        self.config = ConfigManager()

        

        # Set appearance from saved config

        saved_mode = self.config.get_appearance_mode()

        ctk.set_appearance_mode(saved_mode)

        ctk.set_default_color_theme("blue")

        

        # Set modern font (Segoe UI for Windows, similar to SF Pro on macOS)

        self.default_font = ("Segoe UI", 11)

        self.button_font = ("Segoe UI", 10)

        

        # Create main window with DnD support

        self.root = DnDApp()

        self._startup_cwd = os.getcwd()

        self.version_label = version_label.strip()

        title = "Podofilo V2 - PDF Manager"

        if self.version_label:

            title = f"{title} ({self.version_label})"

        self.root.title(title)



        # Set window icon based on appearance mode

        self._set_window_icon()



        # Window geometry state

        self._is_maximized = False

        self._last_normal_geometry: Dict[str, Optional[int]] = {}

        self._apply_saved_geometry()

        self.root.bind("<Configure>", self._on_window_configure)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        

        # Initialize log buffer to capture all logs from start

        self.log_buffer = []

        self._setup_log_capture()

        

        # Initialize managers

        self.viewer = PdfViewer()

        self.section_manager = SectionManager()

        self.viewer.section_manager = self.section_manager  # Link for excluding Borrados

        self.pdf_numbering = PdfNumbering()

        self.config = ConfigManager()



        # Ingest pipeline (API única de entrada de PDFs)

        self.ingest_pipeline = IngestPipeline()

        

        # Numbering configuration

        # Numbering position config

        self.numbering_format = "Página %(n) de %(N)"

        self.numbering_position = "bottom-center"

        self.numbering_fontsize = 22

        self.numbering_margin = 30

        # Altura lógica del "hueco" inferior para posiciones bottom-*.

        # Nota: no cambia el tamaño real de la página, solo guía el layout de foliado.

        self.numbering_footer_height_pt = 25

        # Tamaño mínimo permitido al reducir la fuente para evitar solapes en el pie.

        self.numbering_min_fontsize = 11

        # Tamaño objetivo inicial para el algoritmo en posiciones bottom-*.

        # Si no cabe, se reducirá progresivamente hasta el mínimo configurado.

        self.numbering_bottom_start_fontsize = 15

        # Límite vertical: la numeración no debe subir más allá del 40% de la altura de página

        # medido desde abajo. Si no encuentra hueco dentro de esta zona, se usará el fallback.

        self.numbering_bottom_max_upward_ratio = 0.40

        # Desplazamiento máximo hacia arriba cuando el pie inferior ya tiene texto.

        self.numbering_bottom_max_shift_pt = 160

        # Separación extra para dejar aire entre numeración y líneas del pie.

        self.numbering_content_clearance_pt = 4





        # OVE integration state (Dynamic Load)

        self.extensions = load_ove_extension()

        self.ove_service = None

        self.shipment_manager = None

        

        if self.extensions:

            ServiceModule = self.extensions['ServiceModule']

            ManagerClass = self.extensions['Manager']

            

            self.ove_service = ServiceModule.OVEUnificadoService()

            self.shipment_manager = ManagerClass(self.ove_service)

        else:

            self.ove_service = None

            self.shipment_manager = None



        self.shipment_window = None

        

        # Shipment Manager listener for auto-show on error

        self._last_error_count = 0

        if self.shipment_manager:

            self.shipment_manager.add_listener(self._check_shipment_errors)



        self.ove_thread: Optional[threading.Thread] = None

        self.ove_connection_state = "idle"  # idle | connecting | connected | error

        self.ove_box_map: Dict[str, int] = {}

        self.ove_show_browser = self.config.get_ove_show_browser()

        self.ove_last_expediente = self.config.get_ove_last_expediente()

        self.ove_credentials: Optional[tuple[str, str]] = None

        self.download_queue: List[tuple] = []  # Queue for sequential downloads (box, index)

        self.retry_queue: set = set()  # Set of (box, index) for batched retries

        self.retry_debounce_timer: Optional[str] = None  # Timer ID for debouncing



        self._pending_ove_expediente_override: Optional[str] = None

        self._initial_actions = list(initial_actions or [])

        

        # Last directory used for loading files (initialized from config)

        self.last_source_dir = self.config.get_last_loaded_dir()

        

        # Collapse to boxes state - stores original boxes for collapsing back

        self._can_collapse_to_boxes = False

        self._collapsed_boxes_backup = []  # Stores boxes when expanded

        

        # Semaphore for limiting concurrent PDF loads (like OVE downloads)

        self._pdf_load_semaphore = threading.Semaphore(5)  # Max 5 concurrent loads

        

        # Undo/Redo Stacks

        self.undo_stack = []

        self.redo_stack = []

        self.max_stack_size = 50

        

        # State tracking for clean/dirty status using hash of state

        self.last_saved_state = None

        

        # Backdrop Expansion Warmup (Precarga de expansión en segundo plano)

        self._warmup_timer_id = None

        self._is_warmup_running = False

        self._warmed_up_state = None  # { 'hash': ..., 'viewer': ..., 'sections': ... }

        

        # Configure Drag and Drop

        self.root.drop_target_register(DND_FILES)

        self.root.dnd_bind('<<Drop>>', self.drop_files)

        

        # Initialize Watcher Manager

        self.watcher_temp_dir = tempfile.mkdtemp(prefix="podofilo_watch_")

        log.info(f"Watcher temp directory created: {self.watcher_temp_dir}")

        # Carpeta temporal para conversiones de entrada (XML/imagen -> PDF), creada bajo demanda.

        self.xml_conversion_temp_dir: Optional[str] = None

        self.watcher_manager = WatcherManager(self._on_watched_file_detected)

        # Dedupe de eventos del watcher: watchdog puede emitir CREATED+MODIFIED (o varios MODIFIED)

        # para el mismo fichero. Aquí guardamos una pequeña ventana temporal para ignorar duplicados.

        self._recent_watched_files = {}

        self._watched_dedupe_lock = threading.Lock()

        self._watched_files_dedupe_seconds = 2.0

        # Tracking de threads process_worker para poder hacer join en shutdown y evitar

        # borrar el temp dir bajo un worker en vuelo (root cause de "Errno 2" en cierre).

        self._watcher_worker_threads: List[threading.Thread] = []

        self._watcher_worker_threads_lock = threading.Lock()

        self._start_watchers()

        

        # Setup UI

        self._setup_ui()

        

        # Guardar rutas iniciales (filtradas a PDFs/XML/imágenes existentes)

        self._initial_files = []

        if initial_files:

            for file_path in initial_files:

                path = Path(file_path)

                if path.is_file() and path.suffix.lower() in ({".pdf", ".xml"} | SUPPORTED_IMAGE_EXTENSIONS):

                    self._initial_files.append(path)

                else:

                    log.warning("Ruta inicial inválida o no es PDF/XML/imagen soportada: %s", path)



        if self._initial_files:

            self.root.after(200, self._open_initial_files)



        if self._initial_actions:

            delay = 900 if self._initial_files else 200

            self.root.after(delay, lambda: self._handle_external_actions(self._initial_actions))

        

        # Start Single Instance Server

        self.instance_server = InstanceServer(self._on_instance_message)

        self.instance_server.start()



        # Recuperar envíos pendientes de la sesión anterior (si los hay).

        # Se programa con after() para que la UI esté completamente lista.

        if self.shipment_manager:

            self.root.after(800, self._check_pending_shipments)

        

        # --- AUTO-UPDATE: sondeo de cola desde el thread de check de arranque ---
        # El thread (lanzado en main.py) deposita un UpdateInfo o None.
        # Hacemos polling no bloqueante hasta recibir el valor final.
        self._update_queue = update_queue
        self._update_check_attempts = 0
        if self._update_queue is not None:
            self.root.after(500, self._poll_update_queue)
        
        log.info("Application initialized")

    # ------------------------------------------------------------------
    # Auto-update
    # ------------------------------------------------------------------
    def _poll_update_queue(self):
        """Sondea la cola de actualización para mostrar el diálogo si hay novedad."""
        try:
            info = self._update_queue.get_nowait()
        except Exception:
            self._update_check_attempts += 1
            if self._update_check_attempts < 240:  # ~2 min @ 500ms
                self.root.after(500, self._poll_update_queue)
            return

        if info is None:
            return
        try:
            self.show_update_dialog(info)
        except Exception as exc:
            log.warning("No se pudo mostrar el diálogo de actualización: %r", exc)

    def show_update_dialog(self, info):
        """Abre el diálogo modal de actualización disponible."""
        from src.ui.update_dialog import UpdateDialog
        UpdateDialog(
            self.root,
            self.config,
            update_info=info,
            local_version=self.version_label,
        )

    def check_for_updates_now(self):
        """Comprobación manual de actualizaciones (botón de Configuración).

        Lanza un worker en background; al terminar muestra el diálogo de
        update si hay novedad, o un messagebox 'estás actualizado'.
        """
        import threading
        from src.core.updater import fetch_latest

        def _worker():
            try:
                ignored = self.config.get_ignored_update_version()
                info = fetch_latest(self.version_label, ignored_version=ignored)
            except Exception as exc:
                log.warning("Comprobación manual de update falló: %r", exc)
                self.root.after(0, lambda e=exc: self._show_manual_check_error(e))
                return
            self.root.after(0, lambda: self._on_manual_check_done(info))

        threading.Thread(target=_worker, daemon=True).start()

    def _show_manual_check_error(self, exc):
        from tkinter import messagebox
        messagebox.showerror(
            "Actualizaciones",
            f"No se pudo comprobar si hay actualizaciones:\n{exc!r}",
            parent=self.root,
        )

    def _on_manual_check_done(self, info):
        from tkinter import messagebox
        if info is None:
            messagebox.showinfo(
                "Actualizaciones",
                f"Estás usando la última versión de Podofilo V2 ({self.version_label}).",
                parent=self.root,
            )
        else:
            self.show_update_dialog(info)

    def _ove_prepare_docs_for_download(self, docs: List['DocumentInfo']) -> List['DocumentInfo']:

        """Aplica la opción global de NO descargar copias auténticas.



        Importante: NO muta los objetos originales (la UI los guarda en metadata),

        sino que crea copias superficiales con `es_copia_autentica=False`.

        """

        try:

            if not self.config.get_ove_no_descargar_copias_autenticas():

                return list(docs)

        except Exception:

            return list(docs)



        prepared: List['DocumentInfo'] = []

        for d in docs:

            if getattr(d, "es_copia_autentica", False):

                try:

                    d2 = copy.copy(d)

                    setattr(d2, "es_copia_autentica", False)

                    prepared.append(d2)

                except Exception:

                    prepared.append(d)

            else:

                prepared.append(d)

        return prepared



    def _apply_saved_geometry(self):

        """Restore saved window geometry or apply defaults"""

        geometry = self.config.get_window_geometry()

        width = geometry.get("width") or 1400

        height = geometry.get("height") or 900

        x = geometry.get("x")

        y = geometry.get("y")

        self._is_maximized = geometry.get("is_maximized", False)



        # Validar que las coordenadas estén dentro de la pantalla visible

        # (evita que la ventana se abra fuera si se desconectó un monitor)

        if isinstance(x, int) and isinstance(y, int):

            screen_width = self.root.winfo_screenwidth()

            screen_height = self.root.winfo_screenheight()

            # Verificar que al menos parte de la ventana sea visible

            if x < -width + 100 or x > screen_width - 100 or y < -50 or y > screen_height - 100:

                log.warning(

                    "Geometría guardada fuera de pantalla (x=%d, y=%d), centrando ventana",

                    x, y

                )

                x = None

                y = None



        geo_str = f"{width}x{height}"

        if isinstance(x, int) and isinstance(y, int):

            geo_str += f"+{x}+{y}"



        self.root.geometry(geo_str)



        self._last_normal_geometry = {

            "width": width,

            "height": height,

            "x": x,

            "y": y,

        }



        if self._is_maximized:

            # Defer zoom to allow geometry to settle

            self.root.after(100, lambda: self.root.state("zoomed"))



    def _on_window_configure(self, event):

        """Track geometry changes while in normal state"""

        state = self.root.state()

        if state == "zoomed":

            self._is_maximized = True

            return



        if state != "normal":

            return



        self._is_maximized = False

        self._last_normal_geometry = {

            "width": self.root.winfo_width(),

            "height": self.root.winfo_height(),

            "x": self.root.winfo_x(),

            "y": self.root.winfo_y(),

        }



    def _save_window_geometry(self):

        """Persist window geometry via ConfigManager"""

        geometry = self._last_normal_geometry or {

            "width": 1400,

            "height": 900,

            "x": None,

            "y": None,

        }



        is_maximized = self.root.state() == "zoomed" or self._is_maximized

        self.config.set_window_geometry(

            width=int(geometry.get("width", 1400)),

            height=int(geometry.get("height", 900)),

            x=geometry.get("x"),

            y=geometry.get("y"),

            is_maximized=is_maximized,

        )



    def _on_close(self):

        """Handle window close event"""

        try:

            # 1. Close viewer documents to release file handles

            if hasattr(self, 'viewer') and self.viewer:

                try:

                    self.viewer.close_all()

                except Exception as e:

                    log.warning(f"Error closing viewer on exit: {e}")



            # 2. Cleanup OVE downloads

            if hasattr(self, 'ove_service') and self.ove_service:

                self.ove_service.cleanup_downloads()

            

            # 3. Stop Watchers

            if hasattr(self, 'watcher_manager'):

                self.watcher_manager.stop()

            

            # 3b. Join de threads process_worker ANTES del rmtree del temp dir.

            # Root cause de "Errno 2" en cierre: el rmtree borraba watcher_temp_dir

            # mientras un worker estaba entre el chequeo de existencia y el move/save.

            # Join con timeout corto: si un worker sigue vivo (p.ej. fitz bloqueado),

            # logueamos y lo dejamos (daemon) — pero ya NO habrá borrado prematuro del destino.

            if hasattr(self, '_watcher_worker_threads'):

                with self._watcher_worker_threads_lock:

                    workers = list(self._watcher_worker_threads)

                for w in workers:

                    if w.is_alive():

                        w.join(timeout=2.0)

                        if w.is_alive():

                            log.warning(f"Cierre: worker del watcher sigue vivo tras join(2s): {w.name}")

            

            # 4. Cleanup Watcher Temp Dir

            if hasattr(self, 'watcher_temp_dir') and os.path.exists(self.watcher_temp_dir):

                errs = safe_rmtree(self.watcher_temp_dir, label='watcher_temp', logger=log)

                if errs:

                    log.warning(f"Cleaned up watcher temp dir con {errs} errores: {self.watcher_temp_dir}")

                else:

                    log.info(f"Cleaned up watcher temp dir: {self.watcher_temp_dir}")



            # 4a. Cleanup de la carpeta temporal usada para conversiones locales a PDF (XML/imagen).

            if (

                hasattr(self, 'xml_conversion_temp_dir')

                and self.xml_conversion_temp_dir

                and os.path.exists(self.xml_conversion_temp_dir)

            ):

                errs = safe_rmtree(self.xml_conversion_temp_dir, label='ingest_conversion', logger=log)

                if errs:

                    log.warning(f"Cleaned up ingest conversion temp dir con {errs} errores: {self.xml_conversion_temp_dir}")

                else:

                    log.info(f"Cleaned up ingest conversion temp dir: {self.xml_conversion_temp_dir}")



            # 4b. Persistir envíos pendientes/fallidos a disco antes de cerrar.

            # Se guardan en ~/podofilo/pending_shipments/ para recuperarlos al reabrir.

            try:

                if getattr(self, 'shipment_manager', None):

                    pending_dir = Path.home() / "podofilo" / "pending_shipments"

                    self.shipment_manager.save_pending_to_disk(pending_dir)

            except Exception as e:

                log.warning(f"Error guardando envíos pendientes: {e}")



            # 4c. Limpieza de temporales de subidas a OVE.

            # Aquí intentamos borrar incluso la carpeta activa (best-effort).

            if getattr(self, 'shipment_manager', None) and getattr(self.shipment_manager, 'temp_dir', None):

                errs = safe_rmtree(self.shipment_manager.temp_dir, label='ove_uploads_active', logger=log)

                if errs:

                    log.warning(f"Limpieza ove_uploads_active con {errs} errores: {self.shipment_manager.temp_dir}")

            self._cleanup_podofilo_upload_temp_dirs()

                

            # 5. Stop Instance Server

            if hasattr(self, 'instance_server'):

                self.instance_server.stop()

                

            self._save_window_geometry()

            try:

                self.ove_service.detener_servicio()

            except Exception:

                pass

        finally:

            self.root.destroy()

    

    def _on_instance_message(self, msg):

        """Handle files/actions sent from another instance"""

        def process():

            # Focus window

            self.root.deiconify()

            self.root.lift()

            self.root.focus_force()



            files = []

            actions = []

            debug_flag = None



            if isinstance(msg, dict):

                files = msg.get("files", []) or []

                actions = msg.get("actions", []) or []

                debug_flag = msg.get("debug", None)

            elif isinstance(msg, (list, tuple)):

                files = list(msg)



            # Si otra instancia se lanzó con --debug, activamos el modo debug en la instancia ya abierta.

            # No desactivamos debug si viene False/None: es un modo de soporte y se mantiene durante la sesión.

            if debug_flag is True:

                self.debug_mode = True



            if files:

                log.info(f"Cargando {len(files)} archivos desde otra instancia")

                self.ingest_paths(files, source=IngestSource.SINGLE_INSTANCE)



            if actions:

                self._handle_external_actions(actions)

        

        # Schedule to run on main thread

        self.root.after(0, process)

    

    def _open_initial_files(self):

        """Load file(s) passed at startup (PDF/XML/imágenes)."""

        if not self._initial_files:

            return



        try:

            file_list = [str(path) for path in self._initial_files]

            if len(file_list) == 1:

                log.info("Abriendo archivo inicial: %s", file_list[0])

                self.ingest_paths([file_list[0]], source=IngestSource.STARTUP)

            else:

                log.info("Abriendo %d archivo(s) inicial(es) en modo caja", len(file_list))

                self.ingest_paths(file_list, source=IngestSource.STARTUP)

        except Exception as exc:

            log.error("No se pudieron abrir los archivos iniciales: %s", exc, exc_info=True)

            messagebox.showerror(

                "Error", f"No se pudieron abrir los archivos iniciales:\n{exc}"

            )

        finally:

            self._initial_files = []



    def _handle_external_actions(self, actions: list):

        try:

            for act in (actions or []):

                if not isinstance(act, dict):

                    continue

                act_type = act.get("type")

                if act_type == "open_save_dialog":

                    d = act.get("dir")

                    if d:

                        self.show_save_dialog(initial_dir_override=str(d))

                elif act_type == "open_ove_upload_dialog":

                    expe = act.get("expediente")

                    if expe:

                        self._pending_ove_expediente_override = str(expe)

                    self._handle_ove_upload_shortcut(None)

        except Exception:

            pass



    def _load_icons(self):

        """Load UI icons"""

        self.icons = {}

        icon_names = ["folder", "settings", "list", "box", "document", "cloud", "upload", "limpiar_todo", "index"]

        

        # Base path

        if getattr(sys, 'frozen', False):

            base_dir = Path(sys._MEIPASS) / "resources" / "icons"

        else:

            # Assuming src/ui/main_window.py -> src/ui -> src -> root -> resources

            base_dir = Path(__file__).parent.parent.parent / "resources" / "icons"

            

        for name in icon_names:

            try:

                black_path = base_dir / f"{name}_black.png"

                white_path = base_dir / f"{name}_white.png"

                

                if black_path.exists() and white_path.exists():

                    self.icons[name] = ctk.CTkImage(

                        light_image=Image.open(black_path),

                        dark_image=Image.open(white_path),

                        size=(16, 16)

                    )



                    # Iconos específicos para OVE: forzar negro/blanco independientemente del tema.

                    # Esto permite que en tema Light el icono se vea bien dentro del botón cuando el

                    # fondo cambia por estado (conectando/conectado/error).

                    if name == "cloud":

                        self.icons["cloud_force_black"] = ctk.CTkImage(

                            light_image=Image.open(black_path),

                            dark_image=Image.open(black_path),

                            size=(16, 16)

                        )

                        self.icons["cloud_force_white"] = ctk.CTkImage(

                            light_image=Image.open(white_path),

                            dark_image=Image.open(white_path),

                            size=(16, 16)

                        )



                    # Icono específico para EXPANDIR: siempre blanco (tanto en Light como en Dark).

                    # Motivo: dentro del botón, el icono negro se ve mal en tema Light.

                    if name == "document":

                        self.icons["document_force_white"] = ctk.CTkImage(

                            light_image=Image.open(white_path),

                            dark_image=Image.open(white_path),

                            size=(16, 16)

                        )



                    # Icono específico para CAJAS: siempre blanco (tanto en Light como en Dark).

                    # Motivo: dentro del botón, el icono oscuro se ve mal en tema Light.

                    if name == "box":

                        self.icons["box_force_white"] = ctk.CTkImage(

                            light_image=Image.open(white_path),

                            dark_image=Image.open(white_path),

                            size=(16, 16)

                        )

                else:

                    log.warning(f"Icon files not found for {name}")

                    self.icons[name] = None

            except Exception as e:

                log.warning(f"Could not load icon {name}: {e}")

                self.icons[name] = None



            

    def show_shipment_window(self):

        if not self.extensions: return

        

        if not self.shipment_window:

             ShipmentWindow = self.extensions['ShipmentWindow']

             self.shipment_window = ShipmentWindow(self.root, self.shipment_manager)

        self.shipment_window.show()



    def _check_pending_shipments(self):

        """Comprueba si hay envíos pendientes de la sesión anterior en disco.



        Si los hay, los carga en el ShipmentManager y muestra un diálogo

        con opciones: enviar todos, borrar todos, ver envíos o cerrar.

        """

        if not self.shipment_manager:

            return



        pending_dir = Path.home() / "podofilo" / "pending_shipments"

        try:

            count = self.shipment_manager.load_pending_from_disk(pending_dir)

        except Exception as e:

            log.error(f"Error cargando envíos pendientes: {e}")

            return



        if count <= 0:

            return



        # Crear diálogo CTkToplevel con 4 opciones

        dialog = ctk.CTkToplevel(self.root)

        dialog.title("Envíos pendientes")

        dialog.geometry("420x180")

        dialog.resizable(False, False)

        dialog.transient(self.root)

        dialog.grab_set()



        # Centrar en pantalla

        dialog.update_idletasks()

        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 210

        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 90

        dialog.geometry(f"420x180+{x}+{y}")



        # Mensaje informativo

        plural = "envío pendiente" if count == 1 else "envíos pendientes"

        ctk.CTkLabel(

            dialog,

            text=f"Se encontraron {count} {plural}\nde la sesión anterior.",

            font=("Segoe UI", 13),

            wraplength=380,

            justify="center",

        ).pack(pady=(20, 15))



        # Frame de botones

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")

        btn_frame.pack(fill="x", padx=15, pady=(0, 15))



        def on_send_all():

            """Poner todos en cola de envío (retry_failed los pasa de WAIT a cola)."""

            self.shipment_manager.retry_failed()

            dialog.destroy()



        def on_delete_all():

            """Borrar todos los envíos recuperados."""

            self.shipment_manager.clear_all()

            dialog.destroy()



        def on_view():

            """Abrir la ventana de gestión de envíos."""

            dialog.destroy()

            self.show_shipment_window()



        def on_close():

            """No hacer nada; los envíos quedan como WAIT en la lista."""

            dialog.destroy()



        # Botones: Enviar todos | Borrar todos | Ver envíos | Cerrar

        ctk.CTkButton(

            btn_frame, text="Enviar todos", width=95,

            command=on_send_all, **get_button_style("primary")

        ).pack(side="left", padx=3)



        ctk.CTkButton(

            btn_frame, text="Borrar todos", width=95,

            command=on_delete_all, **get_button_style("secondary")

        ).pack(side="left", padx=3)



        ctk.CTkButton(

            btn_frame, text="Ver envíos", width=95,

            command=on_view, **get_button_style("secondary")

        ).pack(side="left", padx=3)



        ctk.CTkButton(

            btn_frame, text="Cerrar", width=80,

            command=on_close, **get_button_style("secondary")

        ).pack(side="right", padx=3)



        # Si cierran con la X, equivale a "Cerrar"

        dialog.protocol("WM_DELETE_WINDOW", on_close)



    def _check_shipment_errors(self):

        """Listener for ShipmentManager updates"""

        # Count current states for visual feedback

        # Count current states for visual feedback

        if not self.extensions: return

        try:

             # Try importing from the new location

             from src.extensions.ove.manager import ShipmentState

        except ImportError:

             return

        

        n_errors = 0

        n_sending = 0

        n_wait = 0

        n_done = 0

        total = 0

        

        with self.shipment_manager._lock:

            total = len(self.shipment_manager.shipments)

            for s in self.shipment_manager.shipments:

                if s.state == ShipmentState.ERROR:

                    n_errors += 1

                elif s.state == ShipmentState.SENDING:

                    n_sending += 1

                elif s.state == ShipmentState.WAIT:

                    n_wait += 1

                elif s.state == ShipmentState.DONE:

                    n_done += 1

        

        # Update visuals on main thread

        self.root.after(0, lambda: self._update_shipment_visuals(n_errors, n_sending, n_wait, n_done, total))



        # If new errors appeared, show window (Original behavior)

        if n_errors > self._last_error_count:

            # Dispatch to main thread to be safe (listener might be called from bg thread)

            self.root.after(0, self.show_shipment_window)

            

        self._last_error_count = n_errors



    def _update_shipment_visuals(self, n_errors, n_sending, n_wait, n_done, total):

        """Update the shipment button color based on state (Semaphore).



        Prioridad de colores:

          - Rojo:    hay errores

          - Naranja: hay envíos en proceso (SENDING)

          - Verde:   todos completados OK (temporal, vuelve al color base tras unos segundos)

          - Base:    estado idle (transparente)

        """

        if not hasattr(self, "btn_shipments"):

            return

            

        theme = get_theme()

        

        # Default style (Ghost / idle)

        new_fg = "transparent"

        new_hover = theme.BG_HOVER

        new_text = theme.TEXT_PRIMARY

        

        # Determine Color Logic (Priority: ERROR > SENDING > SUCCESS > IDLE)

        if n_errors > 0:

            # Rojo: hay errores que requieren atención

            new_fg = theme.ERROR

            new_hover = "#cc3030"

            new_text = "#ffffff"

        elif n_sending > 0:

            # Naranja: hay envíos en proceso de subida

            new_fg = theme.WARNING

            new_hover = "#e08900"

            new_text = "#ffffff"

        elif n_wait > 0:

            # Naranja suave: hay pendientes esperando turno

            new_fg = theme.WARNING

            new_hover = "#e08900"

            new_text = "#ffffff"

        elif n_done > 0 and n_done == total:

            # Verde temporal: todos completados OK

            new_fg = theme.SUCCESS

            new_hover = "#28a745" 

            new_text = "#ffffff"

            # Programar vuelta al color base tras 4 segundos

            self._schedule_shipment_color_reset()

            

        # Apply styles

        try:

            self.btn_shipments.configure(

                fg_color=new_fg,

                hover_color=new_hover,

                text_color=new_text

            )

        except Exception:

            pass



    def _schedule_shipment_color_reset(self):

        """Programa la vuelta del icono de envíos al color base tras unos segundos.



        Si ya hay un timer programado, lo cancela y reprograma (evita acumulación).

        """

        # Cancelar timer anterior si existe

        if hasattr(self, '_shipment_reset_timer') and self._shipment_reset_timer:

            self.root.after_cancel(self._shipment_reset_timer)



        # Volver al color base tras 4 segundos

        self._shipment_reset_timer = self.root.after(4000, self._reset_shipment_color)



    def _reset_shipment_color(self):

        """Restaura el icono de envíos al color base (idle/transparente)."""

        self._shipment_reset_timer = None

        if not hasattr(self, "btn_shipments"):

            return

        theme = get_theme()

        try:

            self.btn_shipments.configure(

                fg_color="transparent",

                hover_color=theme.BG_HOVER,

                text_color=theme.TEXT_PRIMARY

            )

        except Exception:

            pass



    def _setup_ui(self):



        """Setup UI components"""

        self._load_icons()

        

        # Zoom state with discrete levels

        # Niveles de zoom discretos (más predecible y mejor para caché)

        # Base: 150px = 100%. Rango: 50% (75px) a 300% (450px)

        self.zoom_levels = [75, 100, 120, 150, 180, 225, 300, 375, 450]  # pixels de altura

        self.thumbnail_size = self.config.get_thumbnail_size()

        self.min_thumbnail_size = 75   # 50%

        self.max_thumbnail_size = 450  # 300%



        # Zoom de CAJAS (box mode): independiente del de miniaturas.

        # Base: 200px de alto = 100%. Aspect ratio 3:4 (ancho=0.75*alto).

        # Rango: 50% (100px) a 280% (560px).

        self.box_zoom_levels = [100, 130, 160, 200, 240, 300, 380, 460, 560]

        self.box_thumbnail_size = self.config.get_box_thumbnail_size()

        self.min_box_size = 100   # 50%

        self.max_box_size = 560   # 280%

        

        # Asegurar que thumbnail_size está en un nivel válido

        self.thumbnail_size = self._snap_to_zoom_level(self.thumbnail_size)

        

        # Main content area (sin toolbar superior para maximizar espacio)

        # Sin márgenes externos: el contenido ocupa todo el área cliente.

        self.content_frame = ctk.CTkFrame(self.root)

        self.content_frame.pack(side="top", fill="both", expand=True, padx=0, pady=0)

        

        # Virtual Grid

        self.grid = VirtualGrid(self.content_frame, ove_enabled=bool(self.extensions))

        self.grid.pack(fill="both", expand=True)

        # Establecer tamaño directamente (no llamar a set_thumbnail_size durante init)

        self.grid.thumbnail_size = self.thumbnail_size

        # Aplicar tamaño de cajas guardado en config (zoom independiente)

        self.grid.box_thumbnail_size = self.box_thumbnail_size

        

        # Configure Grid Callbacks

        self.grid.on_request_image = self._on_request_image

        self.grid.on_selection_change = self._on_selection_change

        self.grid.on_right_click = self._on_right_click

        self.grid.on_click = self._on_thumbnail_click

        self.grid.on_double_click = self._on_thumbnail_double_click

        self.grid.on_drag_start = self._on_drag_start

        self.grid.on_drag_motion = self._on_drag_motion

        self.grid.on_drag_end = self._on_drag_end

        # Hover de cajas: permite mostrar motivo de error en la barra de estado.

        self.grid.on_box_hover = self._on_box_hover_status

        self.grid.on_split_request = self.split_section_at

        self.grid.on_box_rename_request = self.rename_box

        self.grid.on_box_right_click = self._on_box_right_click

        self.grid.on_header_rename_request = self.rename_section

        self.grid.on_header_right_click = self._on_section_right_click

        

        # Pasar niveles de zoom para precarga inteligente

        self.grid._zoom_levels_for_preload = self.zoom_levels

        

        # Configure Sidebar Callbacks

        if hasattr(self.grid, 'sidebar'):

            self.grid.sidebar.on_section_click = self._on_section_click

            self.grid.sidebar.on_section_right_click = self._on_section_right_click

            # Permite reordenar secciones desde el sidebar (arrastrar arriba/abajo).

            # El callback recibe (section_obj, insert_index).

            self.grid.sidebar.on_section_reorder = self._on_section_reorder

        

        # Restore continuous mode from config

        if self.config.get_continuous_mode():

            self.grid.set_continuous_mode(True)

            self.grid.sidebar.grid_remove()

        

        # Status bar (footer) integrado: mismo "plano" visual + separadores finos estilo Windows

        theme = get_theme()

        self.status_bar = ctk.CTkFrame(

            self.root,

            height=31,

            corner_radius=0,

            fg_color=theme.BG_SECONDARY,

            border_width=0,

        )

        self.status_bar.pack(side="bottom", fill="x", padx=0, pady=0)

        # Evitar que el footer crezca por el tamaño/padding de los hijos.

        self.status_bar.pack_propagate(False)



        # Separador superior del footer (línea fina entre contenido y footer)

        self.status_bar_separator = ctk.CTkFrame(

            self.root,

            height=1,

            fg_color=theme.SEPARATOR,

            corner_radius=0,

        )

        # El separador debe quedar justo encima del footer.

        self.status_bar_separator.pack(side="bottom", fill="x", padx=0, pady=0, before=self.status_bar)



        # Contenedor derecho para poder añadir separadores verticales entre grupos de botones

        # Importante: usamos pack(side="right") para controlar el orden visual (derecha→izquierda)

        self.footer_right = ctk.CTkFrame(self.status_bar, fg_color="transparent", corner_radius=0)

        # Sin margen derecho: el cluster debe quedar pegado al borde derecho

        self.footer_right.pack(side="right", padx=(0, 0))



        # Helper local: separador vertical fino (1px) entre botones/grupos

        def _footer_vsep():

            # Un separador estilo Windows Fotos: línea fina y poco intrusiva

            sep = ctk.CTkFrame(self.footer_right, width=1, height=16, fg_color=theme.SEPARATOR, corner_radius=0)

            # En el cluster derecho, los separadores siguen el mismo sentido de packing (right)

            # Reducimos padding horizontal para que los iconos queden más juntos

            sep.pack(side="right", padx=1, pady=4)

            return sep

        ghost_btn_style = {

            "fg_color": "transparent",

            "text_color": theme.TEXT_PRIMARY,

            "hover_color": theme.BG_HOVER,

        }



        # Botón Abrir (Izquierda)

        self.btn_open = ctk.CTkButton(

            self.status_bar,

            text="",

            image=self.icons.get("folder"),

            command=self.open_pdf,

            width=34,

            height=24,

            font=("Segoe UI", 14),

            **ghost_btn_style

        )

        self.btn_open.pack(side="left", padx=8, pady=2)

        ToolTip(self.btn_open, "Abrir archivo PDF (Ctrl+A)")



        # Status label (izquierda, después del botón)

        self.status_label = ctk.CTkLabel(

            self.status_bar,

            text="Listo - Abre un PDF para empezar",

            anchor="w",

            font=self.default_font

        )

        self.status_label.pack(side="left", padx=10, fill="x", expand=True)

        # Estado del tooltip temporal en barra de estado (hover sobre cajas FAILED).

        self._status_hover_active = False

        self._status_hover_prev_text = ""

        self._status_hover_text = ""

        

        # ---------------------------------------------------------------

        # Controles de zoom del EDITOR (anclados al centro exacto del footer).

        # Solo se muestran cuando está activa la vista de edición

        # (hoja a tamaño completo, tecla E / "Editar páginas seleccionadas").

        # ---------------------------------------------------------------

        self.footer_zoom = ctk.CTkFrame(self.status_bar, fg_color="transparent", corner_radius=0)

        # Se crea oculto (sin place); se muestra en open_page_editor_for_page con

        # place(relx=0.5, anchor="center"), de modo que queda SIEMPRE centrado en

        # el footer, sin desplazarse según el ancho del texto de estado.

        # Se oculta de nuevo en _close_editor.

        # Estado de visibilidad de los botones de zoom (se ocultan si no caben)

        self._zoom_visible = False

        # Texto completo del estado (sin truncar). El label muestra una versión

        # recortada con "..." cuando llega a la zona de los botones de zoom.

        self._status_full_text = ""

        



        # Botones en el footer (derecha)

        # Orden visual deseado (Izq -> Der): EXPANDIR/CAJAS | OVE | ENVÍOS | LOG | LIMPIAR TODO | OPCIONES

        # Con pack(side="right"), el primer widget empaquetado queda más a la derecha.

        

        # OPCIONES (derecha del todo)

        self.btn_settings = ctk.CTkButton(

            self.footer_right,

            text="",

            image=self.icons.get("settings"),

            command=self.show_settings,

            width=34,

            height=24,

            font=("Segoe UI", 14),

            **ghost_btn_style

        )

        self.btn_settings.pack(side="right", padx=0, pady=2)

        ToolTip(self.btn_settings, "Configuración de Podofilo")



        _footer_vsep()



        # LIMPIAR TODO (a la izquierda de Opciones)

        self.btn_clear_all = ctk.CTkButton(

            self.footer_right,

            text="",

            image=self.icons.get("limpiar_todo"),

            command=self.clear_all,

            width=34,

            height=24,

            font=("Segoe UI", 14),

            **ghost_btn_style

        )

        self.btn_clear_all.pack(side="right", padx=0, pady=2)

        ToolTip(self.btn_clear_all, "Limpiar todo - Reiniciar aplicación (Ctrl+N)")



        _footer_vsep()



        # LOG (a la izquierda de Limpiar Todo)

        self.btn_log = ctk.CTkButton(

            self.footer_right,

            text="",

            image=self.icons.get("list"),

            command=self.show_log_viewer,

            width=34,

            height=24,

            font=("Segoe UI", 14),

            **ghost_btn_style

        )

        self.btn_log.pack(side="right", padx=0, pady=2)

        ToolTip(self.btn_log, "Visor de Log")



        _footer_vsep()



        # Grupo OVE (OVE + Envíos) a la izquierda del LOG

        self.footer_ove = ctk.CTkFrame(self.footer_right, fg_color="transparent", corner_radius=0)

        self.footer_ove.pack(side="right")



        _footer_vsep()



        # Grupo MODO (expandir/cajas) a la izquierda del grupo OVE

        self.footer_mode = ctk.CTkFrame(self.footer_right, fg_color="transparent", corner_radius=0)

        self.footer_mode.pack(side="right")



        # Botones expandir/colapsar se empaquetan dinámicamente

        self.btn_expand = ctk.CTkButton(

            self.footer_mode,

            # Sin espacio inicial: evita padding artificial a la izquierda del texto

            text="EXPANDIR",

            # Forzamos document_white.png en ambos temas para que siempre se vea bien dentro del botón

            image=self.icons.get("document_force_white") or self.icons.get("document"),

            compound="left",

            command=self.expand_all_boxes,

            # width explícito para evitar el ancho por defecto (demasiado grande)

            width=110,

            height=24,

            font=("Segoe UI", 11),

            fg_color=theme.BUTTON_PRIMARY_BG,

            hover_color=theme.BUTTON_PRIMARY_HOVER,

            text_color=theme.BUTTON_PRIMARY_TEXT,

            # Compactar padding interno para parecerse al botón OVE

            border_spacing=2,

        )



        self.btn_collapse = ctk.CTkButton(

            self.footer_mode,

            # Sin espacio inicial: evita padding artificial a la izquierda del texto

            text="CAJAS",

            # Forzamos box_white.png en ambos temas para que siempre se vea bien dentro del botón

            image=self.icons.get("box_force_white") or self.icons.get("box"),

            compound="left",

            command=self.collapse_to_boxes,

            # width explícito para evitar el ancho por defecto (demasiado grande)

            width=90,

            height=24,

            font=("Segoe UI", 11),

            fg_color=theme.BUTTON_PRIMARY_BG,

            hover_color=theme.BUTTON_PRIMARY_HOVER,

            text_color=theme.BUTTON_PRIMARY_TEXT,

            # Compactar padding interno para parecerse al botón OVE

            border_spacing=2,

        )



        # Envíos vive dentro del grupo OVE y se muestra dinámicamente al conectar

        self.btn_shipments = ctk.CTkButton(

            self.footer_ove,

            text="",

            image=self.icons.get("upload"),

            command=self.show_shipment_window,

            width=34,

            height=24,

            font=("Segoe UI", 14),

            **ghost_btn_style

        )

        ToolTip(self.btn_shipments, "Envíos a OVE")



        if self.extensions:

            self.btn_ove = ctk.CTkButton(

                self.footer_ove,

                text="OVE",

                image=self.icons.get("cloud"),

                compound="right",

                command=self._on_ove_button_click,

                width=80,

                height=24,

                font=("Segoe UI", 11, "bold"),

                fg_color=theme.BUTTON_SECONDARY_BG,

                hover_color=theme.BUTTON_SECONDARY_HOVER,

                text_color=theme.BUTTON_SECONDARY_TEXT,

                border_width=0,

                border_color=theme.BUTTON_SECONDARY_BORDER

            )

            # En el orden Izq->Der, OVE va antes que Envíos (queda a la izquierda)

            self.btn_ove.pack(side="right", padx=0, pady=2)

            ToolTip(self.btn_ove, "Conectar/Descargar desde OVE (Ctrl+O)")

        else:

            self.btn_ove = None



        # Nota: btn_expand/btn_collapse ahora viven en self.footer_mode, y se empaquetan dinámicamente



        # ---------------------------------------------------------------

        # Botones de ZOOM del editor (grupo centrado en el footer)

        # Zoom - | Zoom + | Alternar hoja completa / ancho de ventana

        # ---------------------------------------------------------------

        # El centrado lo resuelve place(relx=0.5) sobre el frame contenedor,

        # no hacen falta spacers laterales.

        self.btn_editor_zoom_out = ctk.CTkButton(

            self.footer_zoom,

            text="−",

            command=self._editor_zoom_out_clicked,

            width=28,

            height=24,

            font=("Segoe UI", 14),

            **ghost_btn_style

        )

        self.btn_editor_zoom_out.pack(side="left", padx=0, pady=2)

        ToolTip(self.btn_editor_zoom_out, "Zoom - (Ctrl + -)")



        self.btn_editor_zoom_in = ctk.CTkButton(

            self.footer_zoom,

            text="+",

            command=self._editor_zoom_in_clicked,

            width=28,

            height=24,

            font=("Segoe UI", 14),

            **ghost_btn_style

        )

        self.btn_editor_zoom_in.pack(side="left", padx=0, pady=2)

        ToolTip(self.btn_editor_zoom_in, "Zoom + (Ctrl + +)")



        self.btn_editor_fit = ctk.CTkButton(

            self.footer_zoom,

            text="⛶",

            command=self._toggle_editor_fit_mode,

            width=28,

            height=24,

            font=("Segoe UI", 13),

            **ghost_btn_style

        )

        self.btn_editor_fit.pack(side="left", padx=(6, 0), pady=2)

        ToolTip(self.btn_editor_fit, "Alternar vista: hoja completa / ancho de ventana")



        # Redistribuye el footer al redimensionar la ventana o al cambiar el

        # ancho del cluster derecho (p.ej. al aparecer/desaparecer ENVÍOS):

        # trunca el texto de estado y muestra/oculta los botones de zoom.

        self.status_bar.bind("<Configure>", self._on_footer_configure)

        self.footer_right.bind("<Configure>", self._on_footer_configure)



        # Keyboard bindings

        self.root.bind("<Return>", self._on_return_key)

        self.root.bind("<BackSpace>", lambda e: self.collapse_to_boxes() if not self.grid.box_mode and self._can_collapse_to_boxes else None)

        self.root.bind("<Left>", self._on_arrow_left)

        self.root.bind("<Right>", self._on_arrow_right)

        self.root.bind("<Up>", self._on_arrow_up)

        self.root.bind("<Down>", self._on_arrow_down)

        self.root.bind("<Control-plus>", self.zoom_in)

        self.root.bind("<Control-equal>", self.zoom_in)

        self.root.bind("<Control-minus>", self.zoom_out)

        self.root.bind("<Control-0>", self.zoom_reset)

        self.root.bind("k", self.toggle_cut_mode)

        self.root.bind("<K>", self.toggle_cut_mode)

        self.root.bind("<Control-k>", self._handle_split_shortcut)

        self.root.bind("<Control-K>", self._handle_split_shortcut)

        self.root.bind("<Escape>", self.deactivate_cut_mode)

        self.root.bind_all("<Shift-S>", self.show_save_dialog)

        self.root.bind("<Control-a>", lambda e: self.open_pdf())

        self.root.bind("<Control-A>", lambda e: self.open_pdf())

        self.root.bind_all("<Control-s>", self._handle_ove_upload_shortcut)

        self.root.bind_all("<Control-S>", self._handle_ove_upload_shortcut)

        self.root.bind_all("<Shift-s>", self.show_save_dialog)

        self.root.bind("<Control-n>", self.clear_all)

        self.root.bind("<Control-N>", self.clear_all)

        self.root.bind("<Control-i>", lambda e: self.generate_index())

        self.root.bind("<Control-I>", lambda e: self.generate_index())

        

        # New keyboard bindings for page operations

        self.root.bind("<space>", self.toggle_selection)

        self.root.bind("<Control-r>", self.rotate_selected)

        self.root.bind("<Control-R>", self.rotate_selected)

        self.root.bind("d", self.duplicate_selected)

        self.root.bind("<D>", self.duplicate_selected)

        self.root.bind("<Shift-D>", self.insert_blank_pages)

        self.root.bind("<Shift-d>", self.insert_blank_pages)

        self.root.bind("<Delete>", self.delete_selected)

        self.root.bind("b", self.mark_selected_blank)

        self.root.bind("<B>", self.mark_selected_blank)

        self.root.bind("<Shift-B>", self.unmark_selected)

        self.root.bind("<Shift-b>", self.unmark_selected)

        self.root.bind("x", self.delete_marked)

        self.root.bind("<X>", self.delete_marked)

        self.root.bind("e", self.open_page_editor)

        self.root.bind("<E>", self.open_page_editor)

        self.root.bind("t", self.add_page_numbering)

        self.root.bind("<T>", self.add_page_numbering)

        self.root.bind("<Shift-T>", self.remove_page_numbering)

        self.root.bind("<Shift-t>", self.remove_page_numbering)

        self.root.bind("f", self.merge_selected_boxes)

        self.root.bind("<F>", self.merge_selected_boxes)

        self.root.bind("m", self.start_keyboard_move)

        self.root.bind("<M>", self.start_keyboard_move)

        self.root.bind("<Control-o>", self._handle_ove_shortcut)

        self.root.bind("<Control-O>", self._handle_ove_shortcut)

        self.root.bind_all("<Shift-o>", self._handle_ove_advanced_shortcut)

        self.root.bind_all("<Shift-O>", self._handle_ove_advanced_shortcut)



        # Undo/Redo

        self.root.bind("<Control-z>", self.undo)

        self.root.bind("<Control-Z>", self.undo)

        self.root.bind("<Control-y>", self.redo)

        self.root.bind("<Control-Y>", self.redo)

        

        # Continuous View Mode

        self.root.bind("<Alt-v>", self.toggle_continuous_mode)

        self.root.bind("<Alt-V>", self.toggle_continuous_mode)



        # Easter egg oculto (Ctrl+Shift+F)

        self.root.bind("<Control-Shift-F>", self._show_easter_egg)

        self.root.bind("<Control-Shift-f>", self._show_easter_egg)



        # Mouse wheel zoom with CTRL

        self.root.bind("<Control-MouseWheel>", self.on_mouse_wheel)

        

        # State

        self.cut_mode = False

        self.editor_active = False

        self.current_editor = None



        self._update_ove_button()



        # Auto-connect OVE if NOT disabled

        if not self.config.get_ove_auto_connect():

            self.root.after(700, self._connect_ove_only)



    def _setup_log_capture(self):

        """Setup logging capture to list buffer"""

        class ListHandler(logging.Handler):

            def __init__(self, buffer_list):

                super().__init__()

                self.buffer = buffer_list

            

            def emit(self, record):

                try:

                    msg = self.format(record)

                    self.buffer.append(msg)

                    # Limit buffer size

                    if len(self.buffer) > 1000:

                        self.buffer.pop(0)

                except Exception:

                    self.handleError(record)

        

        handler = ListHandler(self.log_buffer)

        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

        logging.getLogger().addHandler(handler)







    # ============================================================

    # OVE INTEGRATION

    # ============================================================



    def _update_ove_button(self):

        if not getattr(self, "btn_ove", None):

            return

        state = getattr(self, "ove_connection_state", "idle")

        

        # Determinar texto según estado y modo de conexión

        if state == "connected" and getattr(self, 'ove_service', None) and self.ove_service.modo:

            modo = self.ove_service.modo.capitalize()  # "oficina" -> "Oficina"

            text = f"OVE ({modo})"

        else:

            text_map = {

                "idle": "OVE",

                "connecting": "Conectando...",

                "connected": "OVE",

                "error": "OVE ⚠",

            }

            text = text_map.get(state, "OVE")

        

        # Colors using theme - OVE button state colors

        theme = get_theme()

        color_map = {

            "idle": (theme.BUTTON_SECONDARY_BG, theme.BUTTON_SECONDARY_HOVER, theme.BUTTON_SECONDARY_TEXT),

            "connecting": (theme.WARNING, "#cc8800", "#ffffff"),

            "connected": (theme.BUTTON_PRIMARY_BG, theme.BUTTON_PRIMARY_HOVER, theme.BUTTON_PRIMARY_TEXT),

            "error": (theme.ERROR, "#cc3030", "#ffffff"),

        }

        fg, hover, text_color = color_map.get(state, (theme.BUTTON_SECONDARY_BG, theme.BUTTON_SECONDARY_HOVER, theme.BUTTON_SECONDARY_TEXT))

        self.btn_ove.configure(text=text, fg_color=fg, hover_color=hover, text_color=text_color)



        # En tema Light: si OVE está desconectado (idle) usar nube negra; en cualquier otro estado usar nube blanca.

        # En tema Dark mantenemos el comportamiento actual (icono adaptativo al tema).

        try:

            appearance = ctk.get_appearance_mode()

        except Exception:

            appearance = None



        if appearance == "Light":

            if state == "idle":

                icon = self.icons.get("cloud_force_black") or self.icons.get("cloud")

            else:

                icon = self.icons.get("cloud_force_white") or self.icons.get("cloud")

            if icon is not None:

                self.btn_ove.configure(image=icon)

        else:

            icon = self.icons.get("cloud")

            if icon is not None:

                self.btn_ove.configure(image=icon)

        

        # Gestión de visibilidad del botón de Envíos

        if state == "connected":

            if not self.btn_shipments.winfo_ismapped():

                # Mostrar Envíos dentro del grupo OVE.

                # En el layout (derecha→izquierda) usamos pack(side="right").

                # Para conseguir (izq→der) ENVÍOS | OVE, hay que empaquetar ENVÍOS primero

                # y forzar luego el re-pack de OVE para que vuelva a quedar a la derecha.

                self.btn_shipments.pack(side="right", padx=1, pady=2)

                try:

                    self.btn_ove.pack_forget()

                    self.btn_ove.pack(side="right", padx=1, pady=2)

                except Exception:

                    pass

        else:

            if self.btn_shipments.winfo_ismapped():

                self.btn_shipments.pack_forget()



    def _set_window_icon(self):

        """Set window icon"""

        try:

            # Handle path for dev vs frozen (PyInstaller)

            if getattr(sys, 'frozen', False):

                base_path = sys._MEIPASS

            else:

                base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            

            icon_path = os.path.join(base_path, "resources", "podofilo.ico")

            

            if os.path.exists(icon_path):

                self.root.iconbitmap(icon_path)

            else:

                log.warning(f"Icon file not found at: {icon_path}")

        except Exception as e:

            log.warning(f"Could not set window icon: {e}")



    def _set_ove_state(self, state: str, message: Optional[str] = None):

        self.ove_connection_state = state

        self._update_ove_button()

        if message:

            self.update_status(message)



    def _on_ove_button_click(self):

        # Si hay error, el botón intenta reconectar

        self._connect_ove_only()



    def _connect_ove_only(self):

        """Connect to OVE without downloading"""

        if self.ove_thread and self.ove_thread.is_alive():

            return

        

        state = getattr(self, "ove_connection_state", "idle")

        

        # Si está en estado ERROR, forzar reinicio del servicio

        if state == "error":

            log.info("Estado ERROR detectado. Reiniciando servicio OVE completo...")

            self.update_status("Reiniciando conexión OVE...")

            try:

                self.ove_service.detener_servicio()

                # Factory logic

                Factory = self.extensions['ServiceModule'].OVEUnificadoService

                self.ove_service = Factory()

                self.shipment_manager.ove_service = self.ove_service # Update linkage

            except Exception as e:

                log.error(f"Error reiniciando servicio: {e}")

                

            self._set_ove_state("idle")

            state = "idle"

            

        # If already connected, do nothing

        if state == "connected":

             self.update_status("Ya conectado a OVE")

             return



        creds = self._request_ove_credentials()

        if not creds:

            return

            

        self.ove_credentials = creds

        

        def worker():

            try:

                usuario, password = self.ove_credentials

                self.root.after(0, lambda: self._set_ove_state("connecting", "Conectando a OVE…"))

                try:

                    modo = self.ove_service.modo

                    if not modo:

                        # Refresh config to pick up debug changes

                        self.ove_show_browser = self.config.get_ove_show_browser()

                        modo = self.ove_service.conectar(

                            usuario,

                            password,

                            mostrar_navegador=self.ove_show_browser,

                        )

                    self.root.after(0, lambda: self._set_ove_state("connected", f"OVE conectado ({modo})"))

                except Exception as exc:

                    try:

                        if self.extensions and 'ServiceModule' in self.extensions:

                            self.extensions['ServiceModule'].delete_credentials(usuario)

                    except Exception:

                        pass

                    err_msg = f"Error de conexión: {exc}"

                    self.root.after(0, lambda: self._on_ove_error(err_msg))

                    return

            finally:

                self.ove_thread = None



        self.ove_thread = threading.Thread(target=worker, daemon=True)

        self.ove_thread.start()



    def _start_ove_download_docs_thread(self, expediente: str, documentos: List['DocumentInfo']):

        """Inicia descarga de una lista de DocumentInfo ya consultada (modo avanzado)."""

        if not self.ove_credentials:

            return



        def worker():

            try:

                # AUTO-RECONNECT logic for DOWNLOAD

                current_state = getattr(self, "ove_connection_state", "idle")

                if current_state == "error":

                    log.info("Auto-reconnecting OVE due to previous error state...")

                    try:

                        self.ove_service.detener_servicio()

                        Factory = self.extensions['ServiceModule'].OVEUnificadoService if self.extensions else None

                        self.ove_service = Factory() if Factory else self.ove_service

                        self.shipment_manager.ove_service = self.ove_service

                    except:

                        pass

                    self.root.after(0, lambda: self._set_ove_state("idle"))



                usuario, password = self.ove_credentials

                self.root.after(0, lambda: self._set_ove_state("connecting", "Conectando a OVE…"))

                try:

                    modo = self.ove_service.modo

                    if not modo:

                        modo = self.ove_service.conectar(

                            usuario,

                            password,

                            mostrar_navegador=self.ove_show_browser,

                        )

                    self.root.after(0, lambda: self._set_ove_state("connected", f"OVE conectado ({modo})"))

                except Exception as exc:

                    try:

                        if self.extensions and 'ServiceModule' in self.extensions:

                            self.extensions['ServiceModule'].delete_credentials(usuario)

                    except Exception:

                        pass

                    err_msg = f"Error de conexión: {exc}"

                    self.root.after(0, lambda: self._on_ove_error(err_msg))

                    return



                if not documentos:

                    self.root.after(0, lambda: self.update_status("No se encontraron documentos en el expediente"))

                    return



                self.root.after(0, lambda: self._prepare_remote_boxes(expediente, documentos))



                def progreso(doc, estado, path):

                    self.root.after(0, lambda d=doc, e=estado, p=path: self._update_remote_box_state(d, e, p))



                try:

                    docs_to_download = self._ove_prepare_docs_for_download(documentos)

                    self.ove_service.descargar_documentos(docs_to_download, progreso=progreso, timeout=5.0)

                except Exception as exc:

                    err_msg = f"Descarga interrumpida: {exc}"

                    self.root.after(0, lambda: self._on_ove_error(err_msg))

                    return



                self.root.after(0, self._check_remote_completion)

            finally:

                self.ove_thread = None

                self.root.after(0, self._flush_retry_batch)

                self.root.after(0, self._process_download_queue)



        self.ove_thread = threading.Thread(target=worker, daemon=True)

        self.ove_thread.start()



    def _open_ove_advanced_download_dialog(self):

        if not self.extensions:

            return



        creds = self._request_ove_credentials()

        if not creds:

            return

        self.ove_credentials = creds



        DownloadDialog = self.extensions.get('DownloadAdvancedDialog')

        if not DownloadDialog:

            return



        ServiceModule = self.extensions['ServiceModule']



        def on_review(expediente: str):

            # Validar que haya conexión (si no, conectar)

            usuario, password = self.ove_credentials

            if not self.ove_service.modo:

                self.ove_service.conectar(usuario, password, mostrar_navegador=self.ove_show_browser)

            docs = self.ove_service.consultar_expediente(expediente)

            # Pasamos a UI solo nombre/descripcion/fecha y la referencia al doc

            items = []

            for d in docs:

                items.append({

                    'doc': d,

                    'name': getattr(d, 'nombre', ''),

                    'description': getattr(d, 'descripcion', '') or '',

                    'date': getattr(d, 'fecha', '') or '',

                    'checked': True,

                })

            return items



        def on_download(expediente: str, selected_items: List[dict]):

            # Guardar último expediente

            self.ove_last_expediente = expediente

            self.config.set_ove_last_expediente(expediente)



            docs = [it['doc'] for it in selected_items if it.get('doc')]

            if not docs:

                return

            self._start_ove_download_docs_thread(expediente, docs)



        def on_open_simple():

            self._trigger_ove_download()



        DownloadDialog(

            self.root,

            initial_expediente=self.ove_last_expediente or "",

            on_review=on_review,

            on_download=on_download,

            on_open_simple=on_open_simple,

            expandir_expediente=self._expandir_expediente,

        )



    def _on_ove_error(self, message: str):

        """Handle OVE error: Log full message, show simplified status"""

        log.error(f"OVE Error Occurred: {message}")

        

        # Simplify message for UI (Title or first line only, max length)

        # Remove traceback-like info if present

        clean_msg = str(message)

        if "Traceback" in clean_msg:

             clean_msg = "Error interno (ver log)"

        elif "\n" in clean_msg:

             clean_msg = clean_msg.split("\n")[0]

             

        if len(clean_msg) > 80:

             clean_msg = clean_msg[:77] + "..."

             

        self._set_ove_state("error", f"Error: {clean_msg}")



    def _handle_ove_shortcut(self, event=None):

        if not self.extensions: return "break"

        self._trigger_ove_download()

        return "break"



    def _handle_ove_advanced_shortcut(self, event=None):

        if not self.extensions:

            return "break"

        try:

            w = getattr(event, "widget", None)

            if w is not None:

                cls = str(w.winfo_class()).lower()

                if "entry" in cls or "text" in cls:

                    return

        except Exception:

            pass

        self._open_ove_advanced_download_dialog()

        return "break"



    def _handle_ove_upload_shortcut(self, event=None):

        """Maneja CTRL+S para subir documentos a OVE (con auto-conexión)"""

        if not self.extensions: return "break"

        

        # Verificar si hay documentos/páginas cargadas

        has_items = (len(self.grid.document_boxes) > 0) if self.grid.box_mode else (self.viewer.get_page_count() > 0)

        if not has_items:

            return "break"

        

        # 1. Verificar conexión

        state = getattr(self, "ove_connection_state", "idle")

        

        # Si estamos conectados, proceder

        if state == "connected":

            self._show_ove_upload_dialog()

            return "break"

            

        # Si no está conectado, intentar conectar

        if self.ove_thread and self.ove_thread.is_alive():

            messagebox.showinfo("Ocupado", "Hay otra operación OVE en curso.")

            return "break"

            

        # Pedir credenciales

        creds = self._request_ove_credentials()

        if not creds:

            return "break"

            

        self.ove_credentials = creds

        self.update_status("Conectando a OVE para subir...")

        

        # Iniciar conexión en hilo

        def connect_worker():

            try:

                # RECONNECT LOGIC FOR UPLOAD (same as _connect_ove_only logic)

                current_state = getattr(self, "ove_connection_state", "idle")

                if current_state == "error":

                     log.info("Auto-reconnecting OVE due to previous error state...")

                     try: 

                         self.ove_service.detener_servicio()

                         self.ove_service = OVEUnificadoService()

                         self.shipment_manager.ove_service = self.ove_service

                     except: pass

                     self.root.after(0, lambda: self._set_ove_state("idle"))



                usuario, password = self.ove_credentials

                self.root.after(0, lambda: self._set_ove_state("connecting", "Conectando a OVE..."))

                

                # Intentar conectar

                modo = self.ove_service.modo

                if not modo:

                    modo = self.ove_service.conectar(

                        usuario, 

                        password, 

                        mostrar_navegador=self.ove_show_browser

                    )

                

                self.root.after(0, lambda: self._set_ove_state("connected", f"OVE conectado ({modo})"))

                

                # Al terminar, lanzar el diálogo de subida en el hilo principal

                self.root.after(0, self._show_ove_upload_dialog)

                

            except Exception as e:

                log.error(f"Error connecting for upload: {e}")

                err_clean = str(e).split('\n')[0]

                self.root.after(0, lambda: self._on_ove_error(f"Error conexión auto: {err_clean}"))



        # START THE THREAD

        threading.Thread(target=connect_worker, daemon=True).start()



    # ============================================================

    # FOLDER WATCHER AND AUTOMATION

    # ============================================================



    def _start_watchers(self):

        """Start monitoring configured folders"""

        folders = self.config.get_watched_folders()

        if not folders:

            return

            

        self.watcher_manager.start()

        patterns = self.config.get_watch_patterns()

        count = 0

        for folder in folders:

            if Path(folder).exists():

                self.watcher_manager.add_watch(folder, patterns)

                count += 1

            else:

                log.warning(f"Watched folder does not exist: {folder}")

        

        if count > 0:

            log.info(f"Monitoring {count} folders for new files matching {patterns}")



    def _on_watched_file_detected(self, file_path: str):

        """Callback from WatcherManager (runs on thread)"""

        # NOTA: este callback llega desde el hilo del watcher.

        # Hacemos dedupe rápido aquí para evitar dobles importaciones por eventos duplicados.

        import time

        now = time.monotonic()

        try:

            with self._watched_dedupe_lock:

                last_seen = self._recent_watched_files.get(file_path)

                if last_seen is not None and (now - last_seen) < self._watched_files_dedupe_seconds:

                    log.info(f"Watcher dedupe: ignorando evento duplicado para {file_path}")

                    return

                self._recent_watched_files[file_path] = now

        except Exception:

            # Si por algún motivo el dedupe falla, no bloqueamos la importación.

            pass



        def process_worker():

            # Tracking de threads: permite hacer join en shutdown antes de borrar el temp dir.

            this_thread = threading.current_thread()

            with self._watcher_worker_threads_lock:

                self._watcher_worker_threads.append(this_thread)

            try:

                # Actualizar directorio cargado (esto es rápido, se puede quedar aquí o ir al main thread)

                try:

                    folder = str(Path(file_path).parent)

                    self.root.after(0, lambda: self._update_last_dir(folder))

                except Exception:

                    pass

                

                target_path_local = file_path



                # Importante (bug impresora/oviscapto): algunas impresoras/escáneres pueden

                # reescribir el mismo nombre de fichero en la carpeta vigilada. Si el usuario

                # expande → se colapsa a cajas → re-expande, el sistema puede reabrir el PDF desde

                # su ruta original, y si ese fichero ya fue reescrito, "desaparece" el documento previo.

                # Solución: trabajar SIEMPRE sobre una copia temporal única (ruta estable) en watcher_temp_dir.

                try:

                    if not hasattr(self, 'watcher_temp_dir') or not os.path.exists(self.watcher_temp_dir):

                        self.watcher_temp_dir = tempfile.mkdtemp(prefix="podofilo_watch_")

                except Exception as e:

                    log_fs_error(log, e, "ensure_watcher_temp_dir_create", src=file_path)

                    

                # Comportamiento fijo del watcher:

                # siempre mover el archivo a temporal para que desaparezca del origen

                # (evita reimportaciones al reiniciar la aplicación).

                try:

                        # Re-check + recrear el temp dir justo antes del move/save (robustez contra

                        # el root cause: cleanup de shutdown puede borrar watcher_temp_dir entre el

                        # chequeo de arriba y la escritura). No es reintento: garantiza destino.

                        try:

                            ensure_temp_dir(self.watcher_temp_dir, label="watcher_temp", logger=log)

                        except OSError as e:

                            log_fs_error(log, e, "ensure_watcher_temp_dir", src=file_path,

                                         dst=self.watcher_temp_dir)

                            raise

                        

                        # Preparar destino temporal

                        original_name = Path(file_path).name

                        target_path_obj = Path(self.watcher_temp_dir) / original_name

                        

                        # Handle name collisions

                        counter = 1

                        stem = target_path_obj.stem

                        suffix = target_path_obj.suffix

                        while target_path_obj.exists():

                            target_path_obj = Path(self.watcher_temp_dir) / f"{stem}_{counter}{suffix}"

                            counter += 1

                        

                        target_path_local = str(target_path_obj)

                        

                        # --- OPTIMIZATION LOGIC ---

                        if self.config.get_watch_optimize_import():

                            try:

                                log.info(f"Optimizing file on import (async): {file_path}")

                                import fitz

                                doc_opt = fitz.open(file_path)

                                doc_opt.save(target_path_local, garbage=4, deflate=True)

                                doc_opt.close()

                                

                                # Si se guardó bien, borrar original

                                if os.path.exists(target_path_local) and os.path.getsize(target_path_local) > 0:

                                    try:

                                        os.remove(file_path)

                                    except Exception as del_err:

                                        log_fs_error(log, del_err, "delete_original",

                                                     src=file_path, level=logging.WARNING)

                                    log.info(f"File optimized and moved: {target_path_local}")

                                else:

                                    raise Exception("Optimized file is empty or missing")

                                    

                            except Exception as opt_err:

                                log_fs_error(log, opt_err, "fitz_open_optimize",

                                             src=file_path, dst=target_path_local)

                                # Fallback: simple move

                                if os.path.exists(target_path_local):

                                    try: os.remove(target_path_local)

                                    except Exception: pass

                                try:

                                    import shutil

                                    shutil.move(file_path, target_path_local)

                                except Exception as move_err:

                                    log_fs_error(log, move_err, "move_watched",

                                                 src=file_path, dst=target_path_local)

                                    raise

                        else:

                            # Simple move (No optimization)

                            try:

                                import shutil

                                shutil.move(file_path, target_path_local)

                                log.info(f"Moved watched file to temp (raw): {target_path_local}")

                            except Exception as move_err:

                                log_fs_error(log, move_err, "move_watched",

                                             src=file_path, dst=target_path_local)

                                raise

                        

                except Exception as e:

                    log_fs_error(log, e, "watcher_process", src=file_path, dst=target_path_local)

                    target_path_local = file_path

                

                # Load the PDF (either original or temp) on Main Thread

                # Unificar la entrada del watcher con el resto de entradas locales.

                # Nota: aquí seguimos pasando un path local (ya estabilizado) para que el pipeline

                # aplique el mismo filtrado/dedupe y marque el origen en metadata.

                self.root.after(0, lambda: self.ingest_paths([target_path_local], source=IngestSource.WATCHER))

                        

            except Exception as e:

                log_fs_error(log, e, "watcher_process_outer", src=file_path)

                self.root.after(0, lambda: self.update_status(f"Error importando {Path(file_path).name}"))

            finally:

                with self._watcher_worker_threads_lock:

                    try:

                        self._watcher_worker_threads.remove(this_thread)

                    except ValueError:

                        pass



        # Launch processing in a dedicated background thread

        worker = threading.Thread(target=process_worker, daemon=True)

        worker.start()



    def _update_last_dir(self, folder):

        """Helper for thread-safe config update"""

        self.last_source_dir = folder

        self.config.set_last_loaded_dir(folder)



    # ============================================================

    # UNDO / REDO SYSTEM

    # ============================================================



    def _get_page_rotations(self):

        """Get rotation of all pages in viewer"""

        rotations = {}

        for idx in range(len(self.viewer.pages)):

            try:

                doc_idx, page_num = self.viewer.pages[idx]

                doc = self.viewer.documents[doc_idx]

                rotations[idx] = doc.get_page(page_num).rotation

            except Exception:

                pass

        return rotations



    def _safe_copy_metadata(self, metadata: dict) -> dict:

        """Create a safe copy of box metadata, excluding non-serializable objects"""

        if not metadata:

            return {}

        

        safe_meta = {}

        # Keys that are safe to copy (primitives, strings, paths, dataclasses)

        safe_keys = {'source', 'path', 'document_id', 'expediente', 'section_id', 

                     'start_page', 'page_count', 'split_config', 'merged_file_paths'}

        

        for key, value in metadata.items():

            if key in safe_keys:

                # These are safe primitives or simple objects

                if isinstance(value, (str, int, float, bool, type(None), list, tuple)):

                    safe_meta[key] = value

                elif hasattr(value, '__dict__'):

                    # Dataclass or simple object - copy as dict

                    try:

                        safe_meta[key] = dict(value.__dict__) if hasattr(value, '__dict__') else value

                    except:

                        pass

            elif key == 'document':

                # DocumentInfo dataclass - convert to dict for safe storage

                if hasattr(value, '__dict__'):

                    safe_meta[key] = dict(value.__dict__)

            # Skip 'doc' (fitz.Document) and any other non-serializable objects

        

        return safe_meta



    def _get_current_state(self):

        """Capture deep copy of current application state"""

        import copy

        state = {

            'box_mode': self.grid.box_mode,

            'selection': list(self.grid.selected_indices), # Works for both modes logic-wise

            'selected_pages': list(self.viewer.selected_pages),

            'marked_pages': list(self.viewer.marked_pages),

        }

        

        if self.grid.box_mode:

            # Snapshot document boxes

            # Deep copy is tricky for objects with complex state like Box.

            # We state-serialize them.

            boxes_state = []

            for box in self.grid.document_boxes:

                # We save the essential state to recreate the box

                box_data = {

                    'name': box.name,

                    'file_path': getattr(box, 'file_path', None), # Path object

                    'state': box.state,

                    'pages': list(box.pages), # Shallow copy of page tuples

                    'metadata': self._safe_copy_metadata(box.metadata),

                    'thumbnail': box.thumbnail

                }

                boxes_state.append(box_data)

            state['boxes'] = boxes_state

        else:

            # Snapshot pages and sections

            state['pages'] = list(self.viewer.pages) # List of tuples, safe

            state['sections'] = copy.deepcopy(self.section_manager.sections)

            state['rotations'] = self._get_page_rotations()

            

        return state



    def _restore_state(self, state):

        """Restore application state from snapshot"""

        if not state:

            return



        box_mode = state.get('box_mode', False)

        

        if box_mode:

            # Restore Box Mode

            from src.pdf.structure import LocalDocumentBox

            

            restored_boxes = []

            for bdata in state.get('boxes', []):

                box = LocalDocumentBox(

                    name=bdata['name'],

                    file_path=bdata.get('file_path'),

                    state=bdata['state']

                )

                box.pages = list(bdata['pages'])

                box.metadata = bdata['metadata']

                box.thumbnail = bdata.get('thumbnail')

                restored_boxes.append(box)

            

            self.grid.set_box_mode(restored_boxes)

            

            # Ensure UI buttons match Box Mode (Show Expand, Hide Collapse)

            if hasattr(self, 'btn_collapse'): self.btn_collapse.pack_forget()

            if hasattr(self, 'btn_expand'): 

                # El botón vive en self.footer_mode y debe respetar el orden derecha→izquierda

                self.btn_expand.pack(in_=self.footer_mode, side="right", padx=2, pady=2)

            

        else:

            # If we are currently in box mode, exit it first to clear state

            if self.grid.box_mode:

                self.grid.exit_box_mode()

                

            # Restore Page Mode

            self.viewer.pages = list(state.get('pages', []))

            self.section_manager.sections = state.get('sections', [])

            

            # Restore rotations (only if changed)

            saved_rotations = state.get('rotations', {})

            current_rotations = self._get_page_rotations()

            

            # Apply rotations

            for idx, rot in saved_rotations.items():

                if idx < len(self.viewer.pages):

                     # Check if different

                     if idx in current_rotations and current_rotations[idx] != rot:

                         try:

                             doc_idx, page_num = self.viewer.pages[idx]

                             doc = self.viewer.documents[doc_idx]

                             # Calculate delta

                             current = current_rotations[idx]

                             delta = rot - current

                             doc.rotate_page(page_num, delta)

                             self.viewer.cache.clear_pdf(str(doc.filepath))

                         except Exception as e:

                             log.warning(f"Error restoring rotation: {e}")



            # Switch to page mode if needed (or refresh)

            self.grid.set_item_count(len(self.viewer.pages))

            self.grid.set_sections(self.section_manager.sections)

            

            # Ensure UI buttons match Page Mode (Hide Expand, Show Collapse)

            if hasattr(self, 'btn_expand'): self.btn_expand.pack_forget()

            if hasattr(self, 'btn_collapse'):

                 # El botón vive en self.footer_mode y debe respetar el orden derecha→izquierda

                 self.btn_collapse.pack(in_=self.footer_mode, side="right", padx=2, pady=2)

            

            # Restore selection/marks

            self.viewer.selected_pages = set(state.get('selected_pages', []))

            self.viewer.marked_pages = set(state.get('marked_pages', []))

            

            # Update grid selection visualization

            self.grid.selected_indices = set(state.get('selection', []))

            

        # Refresh UI

        self.grid._update_layout()

        self.grid.redraw()

        

        # If we had a sidebar, update it

        if hasattr(self.grid, 'sidebar'):

             self.grid.sidebar.redraw()

             

        self.update_status("Deshacer/Rehacer aplicado")



    def add_undo_snapshot(self):

        """Capture state before modification"""

        state = self._get_current_state()

        self.undo_stack.append(state)

        

        # Limit stack size

        if len(self.undo_stack) > self.max_stack_size:

            self.undo_stack.pop(0)

            

        # Clear redo stack on new branch

        self.redo_stack.clear()

        log.debug(f"Undo snapshot added. Stack size: {len(self.undo_stack)}")



    def undo(self, event=None):

        """Undo last action"""

        # Bloqueado en modo Edición: restaurar estado cambiaría las páginas

        # que el editor tiene cargadas.

        if self._grid_action_blocked():

            return "break"

        if not self.undo_stack:

            self.update_status("No hay nada que deshacer")

            return "break"

            

        # Save current state to redo stack

        current_state = self._get_current_state()

        self.redo_stack.append(current_state)

        

        # Pop previous state

        state = self.undo_stack.pop()

        self._restore_state(state)

        

        self.update_status(f"Deshacer ({len(self.undo_stack)} restantes)")

        log.info("Undo performed")

        return "break"



    def redo(self, event=None):

        """Redo last undone action"""

        # Bloqueado en modo Edición (mismo motivo que undo)

        if self._grid_action_blocked():

            return "break"

        if not self.redo_stack:

            self.update_status("No hay nada que rehacer")

            return "break"

            

        # Save current state to undo stack

        current_state = self._get_current_state()

        self.undo_stack.append(current_state)

        

        # Pop next state

        state = self.redo_stack.pop()

        self._restore_state(state)

        

        self.update_status(f"Rehacer ({len(self.redo_stack)} restantes)")

        log.info("Redo performed")

        return "break"



    def _show_ove_upload_dialog(self):

        """Prepara y muestra el diálogo de subida (asume conexión OK)"""

        items_to_upload = [] 

        try:

            if self.grid.box_mode:

                # MODO CAJAS: Listar TODAS las cajas

                # Selección: Si hay cajas seleccionadas, solo esas estarán marcadas por defecto.

                # Si no hay selección, todas marcadas.

                selected_indices = set(self.grid.selected_indices)

                has_selection = len(selected_indices) > 0



                for i, box in enumerate(self.grid.document_boxes):

                   name = box.name

                   if not name.lower().endswith(".pdf"):

                       name += ".pdf"

                    

                   # Estado checked

                   if has_selection:

                       is_checked = i in selected_indices

                   else:

                       is_checked = True



                   items_to_upload.append({

                       'type': 'box',

                       'name': name,

                       'box': box, # Referencia para sacar path o data

                       'checked': is_checked,

                       'expediente': box.metadata.get('expediente')  # Pass detected expediente

                   })

            else:

                # MODO VISOR: Listar TODAS las secciones

                # El usuario se quejaba de que solo salía 1.

                # Las secciones representan los documentos lógicos actuales.

                sections = self.section_manager.sections

                if not sections:

                    messagebox.showinfo("Info", "No hay documentos para subir.")

                    return



                # En modo visor no suele haber "selección de secciones" explícita como tal en el grid

                # (salvo pages selected), así que marcamos todas por defecto.

                # Opcional: Si el usuario tiene páginas seleccionadas que pertenecen a una sección,

                # podríamos marcar solo esa sección? Por ahora todas True.

                

                for section in sections:

                    # Ignorar secciones especiales como Bins/Borrados si las hubiera O secciones vacías

                    if section.is_special or section.page_count == 0:

                        continue

                        

                    name = section.title

                    if not name.lower().endswith(".pdf"):

                        name += ".pdf"

                        

                    items_to_upload.append({

                        'type': 'section',

                        'name': name,

                        'section': section,

                        'checked': True,

                        'expediente': section.metadata.get('expediente')

                    })



            if not items_to_upload:

                messagebox.showinfo("Información", "No hay documentos válidos para subir.")

                return

            

            # --- MEJORA: Detectar expediente común ---

            # Si hay expedientes detectados en los items, usamos el más frecuente como predeterminado

            # en lugar de simplemente el último usado.

            detected_expes = [item.get('expediente') for item in items_to_upload if item.get('expediente')]

            

            default_expediente = self.ove_last_expediente or ""

            if detected_expes:

                try:

                    common_expe = Counter(detected_expes).most_common(1)[0][0]

                    if common_expe:

                        default_expediente = common_expe

                except Exception:

                    pass



            if self._pending_ove_expediente_override:

                default_expediente = self._pending_ove_expediente_override

                self._pending_ove_expediente_override = None

            # ----------------------------------------

            

            # 3. Obtener tipos de firma (recarga fresca con el expediente actual)

            tipos_firma = {}

            if self.ove_service and hasattr(self.ove_service, 'get_tipos_firma'):

                # El endpoint adjuntarDocumento/<exp>.html requiere un

                # expediente válido en la URL; el placeholder "a" provoca

                # HTTP 500. Usamos el expediente expandido para la recarga.

                # Si no hay expediente real, usamos un expediente semilla

                # (año anterior) para poder cargar los tipos igualmente.

                exp_para_tipos = default_expediente or ""

                if exp_para_tipos:

                    try:

                        expandido = self._expandir_expediente(exp_para_tipos)

                        if expandido:

                            exp_para_tipos = expandido

                    except Exception:

                        pass

                if not exp_para_tipos:

                    try:

                        exp_para_tipos = self.ove_service._expediente_semilla()

                    except Exception:

                        exp_para_tipos = ""

                try:

                    # No forzar: si ya se cargaron hoy, se reutiliza la caché.

                    self.ove_service.recargar_tipos_firma(exp_para_tipos)

                except Exception as e:

                    log.warning("No se pudieron recargar tipos de firma al abrir diálogo: %s", e)

                tipos_firma = self.ove_service.get_tipos_firma()

            

            # 4. Mostrar Diálogo

            if self.extensions:

                UploadDialog = self.extensions['UploadDialog']

                UploadDialog(

                    self.root,

                    items=items_to_upload,

                    initial_expediente=default_expediente,

                    on_upload=self._on_ove_dialog_confirmed,

                    expandir_expediente=self._expandir_expediente,

                    tipos_firma=tipos_firma,

                    ove_service=self.ove_service

                )



        except Exception as e:

            log.error("Error preparando subida: %s", e, exc_info=True)

            messagebox.showerror("Error", f"Error preparando subida:\n{e}")





    def _on_ove_dialog_confirmed(self, items_to_upload):

        """Callback cuando el usuario confirma la subida en el diálogo"""

        if items_to_upload:

            primer_expediente = items_to_upload[0].get('expediente', '')

            if primer_expediente:

                self.ove_last_expediente = primer_expediente

                self.config.set_ove_last_expediente(primer_expediente)

        self._start_ove_upload_manager(items_to_upload)



    def _start_ove_upload_manager(self, items_to_upload: List[dict]):

        """Delegar la subida al ShipmentManager persistente"""

        

        # Mostrar la ventana de envíos -> EXPLICITLY REMOVED as per user request

        # self.show_shipment_window()

        

        # Copiar referencias necesarias para el hilo

        # Necesitamos la lista de paginas de las secciones ANTES de entrar al hilo 

        # para evitar race conditions si la UI cambia (aunque el usuario debería esperar).

        # Para cajas es más fácil (reference to box).

        

        prepared_items = []

        for item in items_to_upload:

            p_item = {

                'type': item['type'], 

                'name': item['name'],

                'expediente': item.get('expediente', ''),

                'tipo_firma': item.get('tipo_firma'),

                'tipo_firma_metadata': item.get('tipo_firma_metadata')

            }

            

            if item['type'] == 'box':

                p_item['box'] = item['box']

            elif item['type'] == 'section':

                # Capturar lista de páginas REAL ahora

                section = item['section']

                # slice self.viewer.pages

                start = section.start_page

                end = start + section.page_count

                if start < len(self.viewer.pages):

                    p_item['pages'] = self.viewer.pages[start:end]

                    # DEBUGGING

                    log.info(f"📄 Sección '{section.title}': start={start}, count={section.page_count}, capturadas={len(p_item['pages'])}")

                    for i, (doc_idx, page_num) in enumerate(p_item['pages']):

                        log.info(f"   └─ Página {i}: doc_idx={doc_idx}, page_num={page_num}")

                else:

                    p_item['pages'] = []

            

            prepared_items.append(p_item)



        def prepare_worker():

            temp_dir = Path(self.shipment_manager.temp_dir) # Use manager's temp context or mkdtemp

            # Actually manager creates its own temp dir for processing, but here we need one for staging files provided TO manager.

            # ShipmentManager loads file content into RAM instantly in add_shipment? 

            # Review shipment_manager: add_shipment(..., path) -> reads bytes -> Shipment(data=...)

            # Yes. So we can use a temporary file here and delete it after add_shipment returns.

            

            staging_dir = tempfile.mkdtemp()



            # Obtener opción global: eliminar firmas digitales.

            # Importante: se aplica también a la subida a OVE (no solo a guardar a disco).

            remove_signatures = False

            try:

                remove_signatures = bool(self.config.get_remove_signatures_on_save())

            except Exception:

                remove_signatures = False

            

            try:

                for item in prepared_items:

                    name = item['name']

                    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '.', '_', '-')).strip()

                    if not safe_name.lower().endswith('.pdf'):

                        safe_name += '.pdf'

                        

                    self.root.after(0, lambda: self.update_status(f"Preparando {safe_name}..."))

                    

                    source_path = None

                    temp_file_created = False

                    

                    try:

                        if item['type'] == 'box':

                            box = item['box']

                            

                            # Check if this is a merged box with multiple files

                            if hasattr(box, 'metadata') and box.metadata.get('merged_file_paths'):

                                # Merged box - need to create a combined PDF from all source files

                                import fitz

                                merged_paths = box.metadata['merged_file_paths']

                                dest_path = Path(staging_dir) / safe_name

                                

                                merged_doc = fitz.open()
                                # Mantener referencias fuente vivas hasta guardar el PDF destino.
                                merged_src_docs = []

                                for file_path in merged_paths:

                                    try:

                                        src_doc = fitz.open(file_path)

                                        merged_src_docs.append(src_doc)

                                        merged_doc.insert_pdf(src_doc)

                                    except Exception as e:

                                        log.error(f"Error loading merged file {file_path}: {e}")



                                # Eliminar firmas si está activado (para que el PDF subido salga sin firma).

                                if remove_signatures and merged_doc.page_count > 0:

                                    for page in merged_doc:

                                        for widget in page.widgets():

                                            if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:

                                                page.delete_widget(widget)

                                

                                if merged_doc.page_count > 0:

                                    merged_doc.save(dest_path)

                                    source_path = dest_path

                                    temp_file_created = True

                                # Cerrar fuentes después de guardar/cerrar el destino.
                                for src_doc in merged_src_docs:
                                    try:
                                        src_doc.close()
                                    except Exception:
                                        pass

                                merged_doc.close()

                            

                            # Try physical path for normal boxes

                            elif hasattr(box, 'file_path') and box.file_path:

                                fpath = box.file_path

                                if Path(fpath).exists():

                                    source_path = Path(fpath)

                            

                            # Fallback: check metadata path

                            elif box.metadata and 'path' in box.metadata:

                                fpath = Path(box.metadata['path'])

                                if fpath.exists():

                                    source_path = fpath



                            # Si vamos a subir un PDF que ya existe en disco, y la opción está activada,

                            # generamos una copia temporal sin firmas para evitar que se cuele la firma

                            # (esto cubre el caso en el que antes se usaba el archivo original tal cual).

                            if source_path and source_path.exists() and remove_signatures:

                                try:

                                    import fitz

                                    dest_path = Path(staging_dir) / safe_name

                                    with fitz.open(str(source_path)) as src_doc:

                                        out_doc = fitz.open()

                                        out_doc.insert_pdf(src_doc)

                                        if out_doc.page_count > 0:

                                            for page in out_doc:

                                                for widget in page.widgets():

                                                    if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:

                                                        page.delete_widget(widget)

                                        out_doc.save(dest_path)

                                        out_doc.close()

                                    source_path = dest_path

                                    temp_file_created = True

                                except Exception as e:

                                    log.error(f"Error eliminando firmas de {safe_name}: {e}")

                            

                            # Last resort: generate from pages (e.g. collapsed box)

                            elif box.pages:

                                dest_path = Path(staging_dir) / safe_name

                                self.viewer.save_pages_direct(dest_path, box.pages, silent=True, remove_signatures=remove_signatures)

                                if dest_path.exists():

                                    source_path = dest_path

                                    temp_file_created = True

                                

                        elif item['type'] == 'section':

                            # Generate from pages

                            pages = item.get('pages', [])

                            if pages:

                                dest_path = Path(staging_dir) / safe_name

                                self.viewer.save_pages_direct(dest_path, pages, silent=True, remove_signatures=remove_signatures)

                                if dest_path.exists():

                                    source_path = dest_path

                                    temp_file_created = True

                        

                        # Add to Shipment Manager

                        if source_path and source_path.exists():

                            # Validar tamaño del archivo (máximo 40MB)

                            file_size_mb = source_path.stat().st_size / (1024 * 1024)

                            if file_size_mb >= 40:

                                error_msg = f"El archivo '{safe_name}' tiene un tamaño de {file_size_mb:.1f} MB.\n\nEl tamaño máximo permitido para subir al OVE es de 40 MB.\n\nPor favor, divide el documento en archivos más pequeños."

                                self.root.after(0, lambda msg=error_msg: messagebox.showerror("Archivo demasiado grande", msg))

                                log.warning(f"Archivo {safe_name} rechazado por tamaño: {file_size_mb:.1f} MB")

                                continue

                            

                            exp = item.get('expediente', '')

                            self.shipment_manager.add_shipment(exp, safe_name, source_path, 

                                                              tipo_firma=item.get('tipo_firma'),

                                                              tipo_firma_metadata=item.get('tipo_firma_metadata'))

                        else:

                            log.error(f"Could not prepare source for {safe_name}")

                            

                    except Exception as e:

                        log.error(f"Error processing item {safe_name}: {e}")

            

            finally:

                errs = safe_rmtree(staging_dir, label='export_staging', logger=log)

                if errs:

                    log.warning(f"Staging de export quedó con {errs} ficheros bloqueados: {staging_dir}")

                self.root.after(0, lambda: self.update_status("Envíos añadidos a la cola"))



        threading.Thread(target=prepare_worker, daemon=True).start()





    def _trigger_ove_download(self):

        if self.ove_thread and self.ove_thread.is_alive():

            self.update_status("Descarga OVE en curso…")

            return



        creds = self._request_ove_credentials()

        if not creds:

            return



        expediente = self._prompt_expediente()

        if not expediente:

            return



        self.ove_credentials = creds

        self.ove_last_expediente = expediente

        self.config.set_ove_last_expediente(expediente)

        self._start_ove_download_thread(expediente)



    def _request_ove_credentials(self) -> Optional[tuple[str, str]]:

        if not self.extensions: return None

        

        ServiceModule = self.extensions['ServiceModule']

        get_saved_user = ServiceModule.get_saved_user

        get_saved_password = ServiceModule.get_saved_password

        save_credentials = ServiceModule.save_credentials

        

        usuario = get_saved_user()

        password = get_saved_password(usuario) if usuario else None

        if usuario and password:

            return usuario, password



        CredentialsDialog = self.extensions['CredentialsDialog']

        dialog = CredentialsDialog(

            self.root,

            default_user=usuario or "",

            show_browser_default=self.ove_show_browser,

        )

        result = dialog.get_credentials()

        if not result:

            return None



        usuario = result["usuario"].strip()

        password = result["password"]

        self.ove_show_browser = bool(result.get("show_browser", True))

        save_creds = result.get("save_creds", True)

        

        self.config.set_ove_show_browser(self.ove_show_browser)

        

        if save_creds:

            save_credentials(usuario, password)

            

        return usuario, password



    def _expandir_expediente(self, nexp: str, provincia: int = 38) -> Optional[str]:

        """

        Expande un número de expediente abreviado al formato completo de 15 dígitos.

        

        Formatos soportados:

        - "380020250001234" → completo (15 dígitos): se devuelve tal cual

        - "24/21599"     → Año/Número: año + número → "380020240021599" (Nuevo)

        - "1/251234"     → Equipo/AñoNúmero: equipo + año + número → "380120250001234"

        - "251234"       → Abreviado: año + número → "380020250001234"

        

        Args:

            nexp: Número de expediente (puede ser abreviado)

            provincia: Código de provincia (default 38 para Extranjería)

            

        Returns:

            Expediente expandido de 15 dígitos, o None si formato inválido

        """

        import re

        nexp = nexp.strip().replace(" ", "")

        

        # 1. Completo (15 dígitos)

        if re.fullmatch(r'\d{15}', nexp):

            return nexp



        # 2. Formato con barra "/"

        if "/" in nexp:

            parts = nexp.split("/")

            if len(parts) == 2:

                p1, p2 = parts[0], parts[1]

                if p1.isdigit() and p2.isdigit():

                    v1 = int(p1)

                    

                    # Heurística: Si la primera parte está en el rango de años actuales (19-33), asumimos Año/Numero

                    # Si es menor (ej 1, 2, 3), asumimos Equipo/AñoNúmero

                    if 19 <= v1 <= 33: # Rango años solicitado

                         # Formato: Año/Número (ej: 24/21599)

                         year = v1

                         num = int(p2)

                         return "%02d00%04d%07d" % (provincia, 2000 + year, num)

                    elif len(p2) >= 3:

                        # Formato: Equipo/AñoNúmero (ej: 1/251234)

                        # p2 incluye Año (2 dos dígitos) + Número

                        team = v1

                        year_p2 = int(p2[:2])

                        num_p2 = int(p2[2:])

                        return "%02d%02d%04d%07d" % (provincia, team, 2000 + year_p2, num_p2)



        # 3. Abreviado directo (e.g. 2501234) -> Y=25, Num=01234

        match_abrev = re.fullmatch(r'(\d{2})(\d{1,7})', nexp)

        if match_abrev:

             year, num = match_abrev.groups()

             return "%02d00%04d%07d" % (provincia, 2000 + int(year), int(num))

             

        return None



    def _prompt_expediente(self) -> Optional[str]:

        while True:

            dialog = CenteredInputDialog(

                self.root,

                "Descargar Expediente desde el OVE",

                "Número de Expediente (Formato abreviado, ej: 251234)",

                initial_value=self.ove_last_expediente or "",

                entry_font=("Segoe UI", 14),

                entry_height=34,

                show_advanced=True,

            )

            value = dialog.get_input()

            if value is None:

                return None



            if value == "__advanced__":

                self._open_ove_advanced_download_dialog()

                return None

            

            # Intentar expandir el expediente

            expanded = self._expandir_expediente(value)

            if expanded:

                return expanded

            

            # Si no se pudo expandir, verificar si tiene al menos 10 caracteres

            value = value.strip().replace(" ", "")

            if len(value) >= 10:

                return value

            

            messagebox.showwarning(

                "Expediente inválido",

                "Introduce un número de expediente válido.\n\n"

                "Formatos aceptados:\n"

                "• Completo: 380020250001234 (15 dígitos)\n"

                "• Abreviado: 251234 (año + número)\n"

                "• Con equipo: 1/251234 (equipo/año+número)"

            )



    def _start_ove_download_thread(self, expediente: str):

        if not self.ove_credentials:

            return



        def worker():

            try:

                # AUTO-RECONNECT logic for DOWNLOAD

                current_state = getattr(self, "ove_connection_state", "idle")

                if current_state == "error":

                     log.info("Auto-reconnecting OVE due to previous error state...")

                     try: 

                         self.ove_service.detener_servicio()

                         Factory = self.extensions['ServiceModule'].OVEUnificadoService if self.extensions else None

                         self.ove_service = Factory() if Factory else self.ove_service

                         self.shipment_manager.ove_service = self.ove_service

                     except: pass

                     self.root.after(0, lambda: self._set_ove_state("idle"))



                usuario, password = self.ove_credentials

                self.root.after(0, lambda: self._set_ove_state("connecting", "Conectando a OVE…"))

                try:

                    modo = self.ove_service.modo

                    if not modo:

                        modo = self.ove_service.conectar(

                            usuario,

                            password,

                            mostrar_navegador=self.ove_show_browser,

                        )

                    self.root.after(0, lambda: self._set_ove_state("connected", f"OVE conectado ({modo})"))

                except Exception as exc:

                    try:

                        if self.extensions and 'ServiceModule' in self.extensions:

                            self.extensions['ServiceModule'].delete_credentials(usuario)

                    except Exception:

                        pass

                    err_msg = f"Error de conexión: {exc}"

                    self.root.after(0, lambda: self._on_ove_error(err_msg))

                    return



                try:

                    documentos = self.ove_service.consultar_expediente(expediente)

                except Exception as exc:

                    err_msg = f"Consulta fallida: {exc}"

                    self.root.after(0, lambda: self._on_ove_error(err_msg))

                    return



                if not documentos:

                    self.root.after(0, lambda: self.update_status("No se encontraron documentos en el expediente"))

                    return



                self.root.after(0, lambda: self._prepare_remote_boxes(expediente, documentos))



                def progreso(doc, estado, path):

                    self.root.after(0, lambda d=doc, e=estado, p=path: self._update_remote_box_state(d, e, p))



                try:

                    # Intento inicial: timeout corto (5s) como pidió el usuario

                    docs_to_download = self._ove_prepare_docs_for_download(documentos)

                    self.ove_service.descargar_documentos(docs_to_download, progreso=progreso, timeout=5.0)

                except Exception as exc:

                    err_msg = f"Descarga interrumpida: {exc}"

                    self.root.after(0, lambda: self._on_ove_error(err_msg))

                    return



                self.root.after(0, self._check_remote_completion)

            finally:

                self.ove_thread = None

                # CRITICAL: Check if there are any queued retries waiting (Opportunistic Batching)

                self.root.after(0, self._flush_retry_batch)

                # Also check legacy queue

                self.root.after(0, self._process_download_queue)



        self.ove_thread = threading.Thread(target=worker, daemon=True)

        self.ove_thread.start()



    def _prepare_remote_boxes(self, expediente: str, documentos: List[DocumentInfo]):

        self.update_status(f"Expediente {expediente}: {len(documentos)} documentos encontrados")

        self._ensure_box_mode()

        existing = self.grid.document_boxes.copy() if self.grid.box_mode else []

        start_index = len(existing)

        new_boxes = []

        if not hasattr(self, 'ove_box_map') or self.ove_box_map is None:

            self.ove_box_map = {}

        for offset, doc in enumerate(documentos):

            box = RemoteDocumentBox(

                name=doc.nombre[:60],

                state=BoxState.LOADING,

                progress=0.0,

                source="ove",

                document_id=doc.id,

            )

            box.metadata["document"] = doc

            box.metadata["expediente"] = expediente

            new_boxes.append(box)

            self.ove_box_map[doc.id] = start_index + offset



        combined = existing + new_boxes

        self.grid.set_box_mode(combined)

        self.btn_expand.pack_forget()

        self.btn_collapse.pack_forget()



    def _ensure_box_mode(self):

        if self.grid.box_mode:

            return

        if self.viewer.get_page_count() > 0:

            self.collapse_to_boxes()

        else:

            self.grid.set_box_mode([])



    def _resolve_ove_payload_path_for_preview(self, downloaded_path: Path, box: Optional[RemoteDocumentBox] = None) -> Path:

        """Normaliza un archivo descargado desde OVE para que siempre sea visualizable como PDF.

        Caso clave: OVE puede devolver XML o imágenes desde una URL `.pdf`.
        Para mantener el visor y el grid sin cambios mayores, convertimos esos payloads a PDF temporal.
        """

        resolved_path = Path(downloaded_path)



        # Si el payload real es XML, lo convertimos a PDF temporal para renderizar miniatura y páginas.

        if resolved_path.suffix.lower() == ".xml":

            if box and getattr(box, "metadata", None) is not None:

                # Trazabilidad: guardamos la ruta XML original descargada por OVE.

                box.metadata["original_xml_path"] = str(resolved_path)

            resolved_path = self._convert_xml_to_temp_pdf(resolved_path)



        # Si el payload real es imagen, también lo convertimos a PDF temporal para renderizado.

        elif resolved_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:

            if box and getattr(box, "metadata", None) is not None:

                # Trazabilidad: guardamos la ruta de imagen original descargada por OVE.

                box.metadata["original_image_path"] = str(resolved_path)

            resolved_path = self._convert_image_to_temp_pdf(resolved_path)



        # Validación final vía pipeline (dedupe/normalización de rutas PDF existentes).

        try:

            ingest_res = self.ingest_pipeline.normalize_local_paths(

                source=IngestSource.OVE_DOWNLOAD,

                paths=[resolved_path],

            )

            if ingest_res.normalized_paths:

                resolved_path = ingest_res.normalized_paths[0]

        except Exception:

            # Best-effort: si falla la validación, seguimos con la ruta resuelta actual.

            pass



        return resolved_path



    def _update_remote_box_state(self, doc: DocumentInfo, estado: str, path: Optional[Path]):

        index = self.ove_box_map.get(doc.id)

        log.debug(f"_update_remote_box_state: doc={doc.id}, estado={estado}, index={index}")

        if index is None:

            log.warning(f"Doc {doc.id} no encontrado en ove_box_map")

            return

        box = self.grid.get_box_at(index)

        if not box:

            log.warning(f"Box no encontrado en index {index}")

            return



        if estado == "downloading":

            box.progress = 0.4

            box.state = BoxState.LOADING

        elif estado == "success":

            box.progress = 1.0

            box.state = BoxState.LOADED

            if path:

                try:

                    # Unificamos payload OVE (PDF/XML) a un PDF renderizable para la caja remota.

                    path = self._resolve_ove_payload_path_for_preview(path, box=box)

                except Exception as exc:

                    box.set_failed("Error procesando descarga")

                    log.warning("No se pudo preparar archivo descargado de OVE (%s): %s", path, exc)

                    path = None



                if not path:

                    self.grid.update_box_state(index)

                    self.root.after(0, self._trigger_expansion_warmup)

                    return



                box.file_path = path

                box.metadata["path"] = str(path)

                box.metadata["ingest_source"] = IngestSource.OVE_DOWNLOAD.value

                try:

                    doc_pdf = fitz.open(str(path))

                    page_count = len(doc_pdf)

                    

                    # Generar thumbnail de la primera página

                    thumbnail = None

                    if page_count > 0:

                        try:

                            pix = doc_pdf[0].get_pixmap(dpi=72)

                            from PIL import Image

                            thumbnail = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                        except Exception:

                            pass

                    

                    # Cerrar el documento fitz

                    doc_pdf.close()

                    

                    # Crear PageReference para cada página (inmutables y autocontenidas)

                    page_refs = [

                        PageReference(file_path=str(path), page_index=i)

                        for i in range(page_count)

                    ]

                    box.set_loaded_refs(page_refs, thumbnail=thumbnail)

                    log.info(f"OVE download complete: {box.name} with {len(page_refs)} PageReferences")

                except Exception as exc:

                    log.warning("No se pudo preparar vista previa de %s: %s", path, exc)

        elif estado == "error":

            # Auto-Retry Logic

            if box.retries_left > 0:

                box.retries_left -= 1

                log.info(f"Auto-retrying box {box.name} (attempts left: {box.retries_left})")

                

                # Use our new opportunistic retry method

                # We need to run this on the main thread loop to be safe with UI updates

                self.root.after(0, lambda: self._retry_remote_box(box, index))

                return

            

            # If no retries left, then fail for real

            box.set_failed("Error descarga")

            log.info(f"Box {index} ({box.name}) marcado como FAILED (Sold out retries)")

            self._set_ove_state("error", "Fallo en la descarga")





        self.grid.update_box_state(index)

        

        # Disparar precarga tras cambios en cajas remotas (OVE)

        self.root.after(0, self._trigger_expansion_warmup)



    def _update_retry_box_state(self, box: RemoteDocumentBox, index: int, estado: str, path: Optional[Path]):

        """Actualiza el estado de una caja durante un retry (usa índice directo)"""

        if not box:

            return



        if estado == "downloading":

            box.progress = 0.4

            box.state = BoxState.LOADING

        elif estado == "success":

            box.progress = 1.0

            box.state = BoxState.LOADED

            if path:

                try:

                    # En retry aplicamos el mismo tratamiento unificado PDF/XML que en la descarga inicial.

                    path = self._resolve_ove_payload_path_for_preview(path, box=box)

                except Exception as exc:

                    box.set_failed("Error procesando descarga (retry)")

                    log.warning("No se pudo preparar archivo descargado de OVE en retry (%s): %s", path, exc)

                    path = None



                if not path:

                    self.grid.update_box_state(index)

                    self.root.after(0, self._trigger_expansion_warmup)

                    return



                box.file_path = path

                box.metadata["path"] = str(path)

                box.metadata["ingest_source"] = IngestSource.OVE_DOWNLOAD.value

                try:

                    doc_pdf = fitz.open(str(path))

                    page_count = len(doc_pdf)

                    

                    # Generar thumbnail de la primera página

                    thumbnail = None

                    if page_count > 0:

                        try:

                            pix = doc_pdf[0].get_pixmap(dpi=72)

                            from PIL import Image

                            thumbnail = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                        except Exception:

                            pass

                    

                    # Cerrar el documento fitz

                    doc_pdf.close()

                    

                    # Crear PageReference para cada página (inmutables y autocontenidas)

                    page_refs = [

                        PageReference(file_path=str(path), page_index=i)

                        for i in range(page_count)

                    ]

                    box.set_loaded_refs(page_refs, thumbnail=thumbnail)

                    log.info(f"OVE retry complete: {box.name} with {len(page_refs)} PageReferences")

                except Exception as exc:

                    log.warning("No se pudo preparar vista previa de %s: %s", path, exc)

        elif estado == "error":

            # Auto-Retry Logic (also recursively for retries of retries)

            if box.retries_left > 0:

                box.retries_left -= 1

                log.info(f"Auto-retrying box {box.name} (attempts left: {box.retries_left}) [Recursion]")

                

                # Re-queue immediately

                self.root.after(0, lambda: self._retry_remote_box(box, index))

                return



            box.progress = 0.0

            box.state = BoxState.FAILED

            box.error_message = "Fallo en la descarga (retry)"



        self.grid.update_box_state(index)

        

        # Disparar precarga tras cambios en cajas remotas (OVE retry)

        self.root.after(0, self._trigger_expansion_warmup)



    def _check_remote_completion(self):

        if not self.ove_box_map:

            return

        for doc_id in self.ove_box_map:

            idx = self.ove_box_map[doc_id]

            box = self.grid.get_box_at(idx)

            if not box or box.state != BoxState.LOADED:

                break

        else:

            self.update_status("Descarga OVE completada. Usa '📄 EXPANDIR' para volver a las miniaturas.")

            # El botón vive en self.footer_mode y debe respetar el orden derecha→izquierda

            self.btn_expand.pack(in_=self.footer_mode, side="right", padx=2, pady=2)







    def _retry_remote_box(self, box: RemoteDocumentBox, index: Optional[int] = None, force_normal: bool = False):

        """Queue a retry for a failed download (Opportunistic Batching)"""

        doc_info = box.metadata.get("document") if box.metadata else None

        

        if force_normal and doc_info:

            log.info(f"Forzando descarga normal para {box.name} (se deshabilita copia auténtica)")

            doc_info.es_copia_autentica = False



        if not doc_info or not self.ove_credentials:

            return



        if index is None:

            try:

                index = self.grid.document_boxes.index(box)

            except ValueError:

                index = None

        if index is None:

            return



        # Add to retry queue (using set avoids duplicates)

        self.retry_queue.add((box, index))



        # Update visual state immediately to QUEUED

        box.state = BoxState.QUEUED

        self.grid.update_box_state(index)

        self.update_status(f"Reintento encolado para: {box.name}...")



        # Opportunistic Batching: Try to flush immediately

        # If worker is busy, it will just return and this item stays in queue

        # until the worker finishes and calls _flush_retry_batch again.

        self._flush_retry_batch()



    def _flush_retry_batch(self):

        """Process queued retries. If idle, takes ALL pending."""

        # If worker is busy, Do NOTHING. The worker will call us when finished.

        if self.ove_thread and self.ove_thread.is_alive():

            return



        if not self.retry_queue:

            return



        # Use defaults if config missing (though should be set)

        

        # Snapshot and clear queue (Take ALL pending items for parallel download)

        batch = list(self.retry_queue)

        self.retry_queue.clear()

        

        # Remove debounce timer ref if it existed (cleanup)

        if self.retry_debounce_timer:

            try: self.root.after_cancel(self.retry_debounce_timer)

            except: pass

            self.retry_debounce_timer = None



        # Group by timeout level (Incremental timeouts: 15s, 30s)

        # Attempt 2 (retries_left=1) -> 15s

        # Attempt 3 (retries_left=0) -> 30s

        batch_15s = []

        batch_30s = []

        box_map = {} # doc.id -> (box, index)

        

        for box, index in batch:

            doc = box.metadata.get("document")

            if doc:

                box_map[doc.id] = (box, index)

                if getattr(box, 'retries_left', 0) >= 1:

                    batch_15s.append(doc)

                else:

                    batch_30s.append(doc)

                

                # Set to Loading and reset progress for visual feedback

                box.state = BoxState.LOADING

                box.progress = 0.05 

                self.grid.update_box_state(index)



        if not batch_15s and not batch_30s:

            return



        self.update_status(f"Reintentando {len(batch_15s) + len(batch_30s)} documentos...")



        def worker():

            try:

                usuario, password = self.ove_credentials

                try:

                    # Ensure connected

                    if not self.ove_service.modo:

                        self.ove_service.conectar(

                            usuario,

                            password,

                            mostrar_navegador=self.ove_show_browser,

                        )

                except Exception as exc:

                    self.root.after(0, lambda: self._on_ove_error(f"Error reconectando: {exc}"))

                    return



                def progreso(doc, estado, path):

                    # Map back to specific box/index

                    if doc.id in box_map:

                        b, i = box_map[doc.id]

                        self.root.after(0, lambda e=estado, p=path, _b=b, _i=i: self._update_retry_box_state(_b, _i, e, p))

                

                # Execute batches sequentially or in parallel? 

                # Better sequentially to avoid saturating but could be parallel too.

                # Use current threading model (one thread per flush)

                if batch_15s:

                    log.info(f"[Retry] Batch 13s starting for {len(batch_15s)} docs")

                    docs_to_download = self._ove_prepare_docs_for_download(batch_15s)

                    self.ove_service.descargar_documentos(docs_to_download, progreso=progreso, timeout=13.0)

                

                if batch_30s:

                    log.info(f"[Retry] Batch 13s starting for {len(batch_30s)} docs")

                    docs_to_download = self._ove_prepare_docs_for_download(batch_30s)

                    self.ove_service.descargar_documentos(docs_to_download, progreso=progreso, timeout=13.0)



                self.root.after(0, self._check_remote_completion)

                

            finally:

                self.ove_thread = None

                # CRITICAL: Check if new retries came in while we were busy

                if self.retry_queue:

                    self.root.after(0, self._flush_retry_batch)

                # Also check legacy queue if used

                elif self.download_queue:

                    self.root.after(0, self._process_download_queue)



        self.ove_thread = threading.Thread(target=worker, daemon=True)

        self.ove_thread.start()



    def _process_download_queue(self):

        """Process the next item in the download queue if idle"""

        if self.ove_thread and self.ove_thread.is_alive():

            return  # Busy

            

        if not self.download_queue:

            return  # Empty



        box, index = self.download_queue.pop(0)

        doc_info = box.metadata.get("document")

        

        if not doc_info:

            self.root.after(0, self._process_download_queue)

            return



        def worker():

            try:

                usuario, password = self.ove_credentials

                try:

                    if not self.ove_service.modo:

                        self.ove_service.conectar(

                            usuario,

                            password,

                            mostrar_navegador=self.ove_show_browser,

                        )

                except Exception as exc:

                    self.root.after(0, lambda: self._on_ove_error(f"Error reconectando: {exc}"))

                    return



                def progreso(doc, estado, path):

                    # Usar el índice directo en lugar de buscar en ove_box_map

                    self.root.after(0, lambda e=estado, p=path: self._update_retry_box_state(box, index, e, p))

                

                docs_to_download = self._ove_prepare_docs_for_download([doc_info])

                self.ove_service.descargar_documentos(docs_to_download, progreso=progreso)

                self.root.after(0, self._check_remote_completion)

            finally:

                self.ove_thread = None

                # Trigger next item in queue

                self.root.after(0, self._process_download_queue)



        box.state = BoxState.LOADING

        box.progress = 0.0

        self.grid.update_box_state(index)

        

        self.ove_thread = threading.Thread(target=worker, daemon=True)

        self.ove_thread.start()



    def _open_box_file(self, box):

        path = getattr(box, "file_path", None) or (box.metadata.get("path") if box.metadata else None)

        if not path:

            messagebox.showinfo("Archivo no disponible", "La caja no tiene un archivo descargado todavía.")

            return

        path = Path(path)

        if not path.exists():

            messagebox.showwarning("Archivo no encontrado", f"No se encontró el archivo:\n{path}")

            return

        try:

            os.startfile(path)

        except Exception as exc:

            messagebox.showerror("Error", f"No se pudo abrir el archivo:\n{exc}")

    

    def _setup_log_capture(self):

        """Setup log capture to buffer all logs from start"""

        import logging

        

        class BufferHandler(logging.Handler):

            def __init__(self, buffer_list):

                super().__init__()

                self.buffer = buffer_list

                

            def emit(self, record):

                msg = self.format(record)

                self.buffer.append(msg)

        

        # Create and add buffer handler to root logger

        self.buffer_handler = BufferHandler(self.log_buffer)

        self.buffer_handler.setFormatter(logging.Formatter(

            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        ))

        logging.getLogger().addHandler(self.buffer_handler)

        

    @contextlib.contextmanager

    def _preserve_cwd(self):

        cwd = os.getcwd()

        try:

            yield

        finally:

            try:

                os.chdir(cwd)

            except Exception:

                pass



    def _restore_startup_cwd(self):

        try:

            os.chdir(self._startup_cwd)

        except Exception:

            pass



    def _cleanup_podofilo_upload_temp_dirs(self, exclude_dirs: Optional[set[Path]] = None):

        """Elimina carpetas temporales antiguas creadas para subidas a OVE.



        Las subidas usan `tempfile.mkdtemp(prefix="podofilo_uploads_")`, lo que deja carpetas en `%TEMP%`.

        Si la app se cierra de forma inesperada o hay fallos, esas carpetas pueden quedarse.



        - En `Ctrl+N` evitamos borrar la carpeta activa del `ShipmentManager` (puede haber subidas en curso).

        - En cierre de app intentamos borrar todo (best-effort) y no fallamos si Windows bloquea algo.

        """

        exclude_dirs = exclude_dirs or set()



        # Normalizamos rutas para comparar bien incluso si vienen con distinta capitalización / separadores.

        # Usamos os.path.realpath (expande 8.3 → long name y no requiere que el dir exista) +

        # os.path.normcase (ignora mayúsculas en Windows). Esto evita que el exclude falle cuando

        # %TEMP% llega como "JUANC~1.RAM" (nombre corto DOS) y el dir activo se resuelve distinto.

        exclude_resolved: set = set()

        for p in exclude_dirs:

            try:

                exclude_resolved.add(os.path.normcase(os.path.realpath(str(p))))

            except Exception:

                # Si no podemos resolver, aún así lo dejamos en bruto normalizado.

                exclude_resolved.add(os.path.normcase(str(p)))



        temp_root = Path(tempfile.gettempdir())

        prefixes = ("podofilo_",)  # Borrar TODAS las carpetas de Podofilo (watch, uploads, etc.)



        removed = 0

        kept = 0

        errors = 0



        try:

            for entry in temp_root.iterdir():

                # Solo nos interesan carpetas con el prefijo de Podofilo.

                if not entry.is_dir():

                    continue

                if not entry.name.startswith(prefixes):

                    continue



                try:

                    entry_resolved = os.path.normcase(os.path.realpath(str(entry)))

                except Exception:

                    entry_resolved = os.path.normcase(str(entry))



                # Si es la carpeta activa (o una de las excluidas), no la tocamos.

                if entry_resolved in exclude_resolved:

                    kept += 1

                    continue



                errs = safe_rmtree(entry, label='podofilo_uploads', logger=log)

                if errs:

                    errors += errs

                    # Si safe_rmtree no pudo borrar nada, contamos como no removido.

                    if entry.exists():

                        continue

                removed += 1



        except Exception as e:

            # Si el listado del temp falla, lo registramos pero no rompemos el flujo.

            log.warning(f"Error recorriendo %TEMP% para limpiar podofilo_uploads_*: {e}")



        if removed or kept or errors:

            log.info(

                "Limpieza de temp OVE: eliminadas=%s, preservadas=%s, errores=%s (ruta=%s)",

                removed,

                kept,

                errors,

                temp_root,

            )



    def clear_all(self, event=None):

        """Clear all content (Reset application)"""

        # Si el editor está abierto, cerrarlo primero: va a desaparecer todo

        self._close_editor_if_active()

        

        # Exit box mode first (this closes fitz docs in boxes)

        if self.grid.box_mode:

            self.grid.exit_box_mode()

            self.btn_expand.pack_forget()

        

        # Hide collapse button and reset collapse state

        self.btn_collapse.pack_forget()

        self._can_collapse_to_boxes = False

        self._collapsed_boxes_backup = []

        if hasattr(self, '_viewer_pages_backup'):

            self._viewer_pages_backup = None

            self._viewer_docs_backup = None

            self._viewer_doc_paths_backup = None

        

        # Close all documents properly to free memory and release file handles

        if hasattr(self, 'viewer') and self.viewer:

            self.viewer.close_all()

        

        # Reset Viewer

        self.viewer = PdfViewer()

        

        # Reset Section Manager

        self.section_manager = SectionManager()

        self.viewer.section_manager = self.section_manager  # Link for excluding Borrados

        

        # Clear Grid

        self.grid.set_item_count(0)

        self.grid.set_sections([])

        self.grid.selected_indices.clear()

        self.grid.images.clear()  # Limpiar cache de imágenes

        self.grid._pending_renders.clear()  # Limpiar renders pendientes

        self.grid.redraw()

        self.ove_box_map = {}

        

        # Forzar garbage collection para liberar memoria y handles

        import gc

        gc.collect()

        

        # Cleanup OVE downloads on clear

        if getattr(self, 'ove_service', None):

            self.ove_service.cleanup_downloads()



        # Limpiar temporales antiguos (podofilo_*)

        # IMPORTANTE: Excluir carpetas activas para no romper procesos en curso.

        exclude = set()

        if getattr(self, 'shipment_manager', None) and getattr(self.shipment_manager, 'temp_dir', None):

            exclude.add(Path(self.shipment_manager.temp_dir))

        

        if getattr(self, 'watcher_temp_dir', None):

            exclude.add(Path(self.watcher_temp_dir))



        # Evitar borrar el directorio activo de descargas de OVE.

        # En Ctrl+N hacemos limpieza general de %TEMP% (prefijo "podofilo_") y, si no lo excluimos,

        # se elimina `podofilo_ove_downloads` y las siguientes descargas fallan con FileNotFoundError.

        if getattr(self, 'ove_service', None) and getattr(self.ove_service, 'download_dir', None):

            exclude.add(Path(self.ove_service.download_dir))

            

        self._cleanup_podofilo_upload_temp_dirs(exclude_dirs=exclude)



        self._restore_startup_cwd()

        

        self.update_status("Listo - Abre un PDF para empezar")

        self.update_title()

        

        # Reset numbering flag

        self.numbering_applied = False

        

        log.info("Application cleared")



    # ------------------------------------------------------------------

    # Indice de documentos
    # ------------------------------------------------------------------

    _INDEX_SECTION_TITLE = "0 INDICE"

    _INDEX_BOX_NAME = "0 INDICE"



    def generate_index(self, event=None):
        """Genera (o regenera) una pagina de indice con los nombres de los
        documentos actuales y la inserta al principio del expediente.

        Funciona tanto en modo cajas como en modo miniaturas/expandido.
        Si ya existe un indice previo, se elimina y se regenera.
        Antes de generar, aplica auto-numeracion (1_, 2_, 3_) a los nombres.

        Flujo robusto:
        1. Eliminar indice previo (paginas, documento, seccion, cachés)
        2. Auto-numerar secciones restantes
        3. Recopilar nombres + calcular rangos de pagina correctos
        4. Generar PDF con nombre unico (evita colision de cache)
        5. Insertar como caja o seccion
        6. Limpiar cachés y refrescar UI
        """
        from src.pdf.index_page import generate_index_pdf
        from src.pdf.structure import LocalDocumentBox, BoxState, PageReference
        import uuid

        # Cerrar el editor si está abierto: el índice inserta/elimina páginas
        # y invalida la página que esté mostrando el editor.
        self._close_editor_if_active()

        # --- 0. Eliminar indice previo (limpia paginas, doc, seccion, caches) ---
        self._remove_existing_index()

        # --- 1. Auto-numerar secciones/cajas ---
        self._number_sections_after_index()

        # --- 2. Recopilar nombres y rangos de pagina ---
        import re as _re
        _SPLIT_SUFFIX_RE = _re.compile(r'/\d+[pPbBmMkK]$')

        def _strip_split_modifier(name: str) -> str:
            """Quita el sufijo de modificador de split (/6M, /6p, /5k, ...)."""
            return _SPLIT_SUFFIX_RE.sub('', name).strip()

        entry_names: list[str] = []
        page_ranges: list[tuple[int, int]] = []  # (pagina_inicio, pagina_fin) 1-based

        if self.grid.box_mode:
            for box in self.grid.document_boxes:
                if box.name == self._INDEX_BOX_NAME:
                    continue
                entry_names.append(_strip_split_modifier(box.name))
                page_ranges.append((0, 0))  # Sin rangos en modo cajas
        else:
            for section in self.section_manager.get_saveable_sections():
                if section.title == self._INDEX_SECTION_TITLE:
                    continue
                entry_names.append(_strip_split_modifier(section.title))
                pg_start = section.start_page + 1
                pg_end = section.start_page + section.page_count
                page_ranges.append((pg_start, pg_end))

        if not entry_names:
            messagebox.showinfo("Indice", "No hay documentos para generar un indice.")
            return

        # --- 3. Generar PDF con nombre unico ---
        # En modo cajas no hay rangos utiles
        ranges_to_pass = page_ranges if not self.grid.box_mode else None
        if ranges_to_pass and all(s == 0 and e == 0 for s, e in ranges_to_pass):
            ranges_to_pass = None

        try:
            index_pdf_path = generate_index_pdf(
                entry_names,
                page_ranges=ranges_to_pass,
                filename_suffix=uuid.uuid4().hex[:8],
            )
        except Exception as exc:
            log.error(f"Error generando PDF de indice: {exc}")
            messagebox.showerror("Error", f"No se pudo generar el indice:\n{exc}")
            return

        # Guardar referencia al path para limpieza futura
        self._index_pdf_path = str(index_pdf_path)

        # --- 4. Insertar segun modo actual ---
        if self.grid.box_mode:
            self._insert_index_as_box(index_pdf_path)
        else:
            self._insert_index_as_section(index_pdf_path)

        # --- 5. Limpiar cachés de miniaturas ---
        self._clear_index_caches()

        self.update_status(f"Indice generado: {len(entry_names)} documentos listados")

    def _clear_index_caches(self):
        """Limpia todas las cachés que puedan retener miniaturas viejas del indice."""
        # Cache del grid (miniaturas renderizadas)
        self.grid.images.clear()
        self.grid._pending_renders.clear()
        if hasattr(self.grid, 'box_images'):
            self.grid.box_images.clear()
        # Cache del viewer (paginas renderizadas)
        if hasattr(self.viewer, 'clear_cache'):
            self.viewer.clear_cache()
        # Cache global de paginas
        from src.pdf.cache import get_cache
        cache = get_cache()
        if hasattr(self, '_index_pdf_path'):
            cache.clear_pdf(self._index_pdf_path)

    def _index_auto_number(self):
        """Auto-numera las secciones/cajas actuales con prefijo '1 ', '2 ', '3 '...
        Replica la logica del boton autonumero del dialogo de guardado."""
        import re

        def _clean_and_number(name: str, idx: int) -> str:
            """Elimina numeracion previa y aplica nueva."""
            cleaned = re.sub(r'^\d+\s+', '', name)
            return f"{idx} {cleaned}"

        if self.grid.box_mode:
            for idx, box in enumerate(self.grid.document_boxes, start=1):
                if box.name == self._INDEX_BOX_NAME:
                    continue
                box.name = _clean_and_number(box.name, idx)
        else:
            saveable = [
                s for s in self.section_manager.sections
                if not s.is_special and s.page_count > 0
                and s.title != self._INDEX_SECTION_TITLE
            ]
            for idx, section in enumerate(saveable, start=1):
                section.title = _clean_and_number(section.title, idx)

    def _number_sections_after_index(self):
        """Auto-numera cajas/secciones excluyendo la seccion 'Indice'.

        En modo expandido, la seccion 'Indice' es la seccion 0 (si existe).
        En modo cajas, la caja 'Indice' es la caja 0 (si existe).
        """
        import re

        def _clean_and_number(name: str, idx: int) -> str:
            cleaned = re.sub(r'^\d+\s+', '', name)
            return f"{idx} {cleaned}"

        if self.grid.box_mode:
            counter = 1
            for box in self.grid.document_boxes:
                if box.name == self._INDEX_BOX_NAME:
                    continue
                box.name = _clean_and_number(box.name, counter)
                counter += 1
        else:
            counter = 1
            for section in self.section_manager.sections:
                if section.is_special:
                    continue
                if section.page_count <= 0:
                    continue
                if section.title == self._INDEX_SECTION_TITLE:
                    continue
                section.title = _clean_and_number(section.title, counter)
                counter += 1

    def _remove_existing_index(self):
        """Elimina el indice existente (caja o seccion) si esta presente.
        
        En modo expandido, tambien elimina las paginas del viewer y el 
        documento asociado para que no queden paginas huerfanas.
        Limpia caches y elimina archivos temporales antiguos del indice.
        """
        # Limpiar archivo temporal anterior si existe
        old_path = getattr(self, '_index_pdf_path', None)
        if old_path:
            try:
                Path(old_path).unlink(missing_ok=True)
                log.debug(f"Temporal de indice anterior eliminado: {old_path}")
            except Exception:
                pass
            self._index_pdf_path = None
        if self.grid.box_mode:
            # Eliminar caja de indice
            before = len(self.grid.document_boxes)
            self.grid.document_boxes = [
                b for b in self.grid.document_boxes
                if b.name != self._INDEX_BOX_NAME
            ]
            if len(self.grid.document_boxes) < before:
                log.info("Indice previo (caja) eliminado")
            return

        # --- Modo expandido ---
        # Buscar la seccion de indice
        index_section = None
        for s in self.section_manager.sections:
            if s.title == self._INDEX_SECTION_TITLE:
                index_section = s
                break

        if index_section is None:
            return  # No hay indice previo

        idx_start = index_section.start_page
        idx_count = index_section.page_count

        # 1. Recopilar los doc_idx usados por las paginas del indice
        index_doc_indices = set()
        for i in range(idx_start, min(idx_start + idx_count, len(self.viewer.pages))):
            doc_idx, _ = self.viewer.pages[i]
            index_doc_indices.add(doc_idx)

        # 2. Eliminar paginas del viewer
        if idx_count > 0 and idx_start < len(self.viewer.pages):
            del self.viewer.pages[idx_start : idx_start + idx_count]
            log.info(f"Eliminadas {idx_count} paginas del viewer (pos {idx_start})")

        # 3. Cerrar y eliminar los documentos del indice del viewer
        #    Ordenar de mayor a menor para no desplazar indices
        for doc_i in sorted(index_doc_indices, reverse=True):
            if doc_i < len(self.viewer.documents):
                try:
                    self.viewer.documents[doc_i].close()
                except Exception:
                    pass
                self.viewer.documents.pop(doc_i)
                log.info(f"Documento de indice eliminado del viewer (doc_idx={doc_i})")

        # 4. Reindexar doc_idx en viewer.pages tras la eliminacion
        if index_doc_indices:
            sorted_removed = sorted(index_doc_indices)
            for i, (doc_idx, page_num) in enumerate(self.viewer.pages):
                shift = sum(1 for r in sorted_removed if r < doc_idx)
                self.viewer.pages[i] = (doc_idx - shift, page_num)

        # 5. Eliminar seccion del section_manager
        self.section_manager.sections.remove(index_section)

        # 6. Recalcular posiciones de las secciones restantes
        current_page = 0
        for section in self.section_manager.sections:
            if section.is_special:
                continue
            section.start_page = current_page
            current_page += section.page_count
        # Actualizar Borrados si ya existe (sin crearlo)
        for section in self.section_manager.sections:
            if section.is_special and section.id == "deleted":
                section.start_page = current_page
                break

        # 7. Refrescar UI
        # Limpiar caches de miniaturas
        self.grid.images.clear()
        self.grid._pending_renders.clear()
        if self.viewer.pages:
            self.grid.set_item_count(
                len(self.viewer.pages),
                page_sizes=self.viewer.get_all_page_sizes(),
            )
        else:
            self.grid.set_item_count(0)
        self.grid.set_sections(self.section_manager.sections)

        log.info("Indice previo (seccion + paginas + documento) eliminado")

        # Limpiar caches
        self.grid.images.clear()
        self.grid._pending_renders.clear()
        if hasattr(self.grid, 'box_images'):
            self.grid.box_images.clear()
        if hasattr(self.viewer, 'clear_cache'):
            self.viewer.clear_cache()
    def _insert_index_as_box(self, index_pdf_path: Path):
        """Inserta el PDF de indice como caja al principio en modo cajas."""
        from src.pdf.structure import LocalDocumentBox, BoxState, PageReference

        box = LocalDocumentBox(
            name=self._INDEX_BOX_NAME,
            file_path=index_pdf_path,
            state=BoxState.LOADED,
            progress=1.0,
        )
        box.metadata['source'] = 'index'
        box.metadata['is_index'] = True

        # Generar PageReferences y miniatura para la caja
        try:
            import fitz as _fitz
            tmp_doc = _fitz.open(str(index_pdf_path))
            for p in range(len(tmp_doc)):
                box.page_refs.append(
                    PageReference(file_path=str(index_pdf_path), page_index=p)
                )
            # Generar miniatura de la primera pagina
            if len(tmp_doc) > 0:
                pix = tmp_doc[0].get_pixmap(dpi=72)
                from PIL import Image as _PILImage
                thumbnail = _PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
                box.thumbnail = thumbnail
            tmp_doc.close()
        except Exception as exc:
            log.warning(f"No se pudieron generar page_refs/miniatura para el indice: {exc}")

        # Insertar al principio
        self.grid.document_boxes.insert(0, box)
        self.grid.set_box_mode(self.grid.document_boxes)

        # Mostrar boton de expandir si no estaba visible
        if hasattr(self, 'btn_expand'):
            self.btn_expand.pack(in_=self.footer_mode, side="right", padx=2, pady=2)

    def _insert_index_as_section(self, index_pdf_path: Path):
        """Inserta el PDF de indice como primera seccion en modo expandido."""
        from src.pdf.document import PdfDocument
        from src.pdf.structure import Section, PageReference

        # Cargar el documento del indice en el viewer
        try:
            index_doc = PdfDocument(str(index_pdf_path))
            doc_idx = len(self.viewer.documents)
            self.viewer.documents.append(index_doc)

            index_pages = []
            for page_num in range(index_doc.page_count):
                self.viewer.pages.insert(page_num, (doc_idx, page_num))
                index_pages.append(
                    PageReference(file_path=str(index_pdf_path), page_index=page_num)
                )
        except Exception as exc:
            log.error(f"Error cargando PDF de indice en viewer: {exc}")
            messagebox.showerror("Error", f"No se pudo cargar el indice:\n{exc}")
            return

        index_page_count = index_doc.page_count

        # Desplazar secciones existentes
        for section in self.section_manager.sections:
            if section.is_special:
                continue
            section.start_page += index_page_count

        # Actualizar Borrados si ya existe (sin crearlo)
        for section in self.section_manager.sections:
            if section.is_special and section.id == "deleted":
                section.start_page += index_page_count
                break

        # Crear nueva seccion de indice al principio
        index_section = Section(
            id="index",
            title=self._INDEX_SECTION_TITLE,
            start_page=0,
            page_count=index_page_count,
        )
        index_section.metadata['is_index'] = True
        self.section_manager.sections.insert(0, index_section)

        # Refrescar UI
        self.grid.set_item_count(
            len(self.viewer.pages),
            page_sizes=self.viewer.get_all_page_sizes(),
        )
        self.grid.set_sections(self.section_manager.sections)



    def _on_request_image(self, index: int, size: int) -> Image.Image:

        """Callback to fetch image for grid"""

        try:

            # In box mode, don't try to get page thumbnails

            if self.grid.box_mode:

                return None

            

            # Validar índice antes de intentar obtener la imagen

            # IMPORTANTE: Usar len(self.viewer.pages) directamente para evitar condiciones de carrera

            actual_page_count = len(self.viewer.pages)

            if index < 0 or index >= actual_page_count:

                # Silenciosamente ignorar índices fuera de rango (puede ocurrir durante transiciones)

                return None

            

            # Calculate DPI based on size (base 72dpi = 150px)

            base_dpi = 72

            scale_factor = size / 150.0

            dpi = int(base_dpi * scale_factor)

            

            # Use fast rescaling for instant feedback

            # This will use cached images at different DPIs and rescale with BILINEAR

            image = self.viewer.get_page_thumbnail_fast(index, dpi)

            

            # Resize if needed (viewer might return larger image)

            if image.height != size:

                 # Maintain aspect ratio - resize to exact height

                 ratio = size / image.height

                 new_size = (round(image.width * ratio), size)

                 image = image.resize(new_size, Image.Resampling.LANCZOS)

            

            return image

        except IndexError as e:

            # Índice fuera de rango - esto indica un desajuste entre grid.item_count y viewer.pages

            # Loguear para diagnóstico pero no como error crítico

            actual_count = len(self.viewer.pages)

            grid_count = self.grid.item_count

            log.debug(f"IndexError page {index}: viewer has {actual_count} pages, grid expects {grid_count}")

            return None

        except Exception as e:

            # In box mode, this is expected (no pages loaded yet)

            if self.grid.box_mode:

                log.debug(f"Skipping image request in box mode: {index}")

            else:

                # Solo loguear si es un error real (no truncated image durante carga)

                error_str = str(e)

                if "truncated" in error_str.lower():

                    log.debug(f"Page {index} image truncated (loading...): {e}")

                else:

                    log.warning(f"Error getting page image {index}: {e}")

            return None



    def _on_selection_change(self):

        """Sync selection from grid to viewer"""

        if self.grid.box_mode:

            count = len(self.grid.selected_indices)

            if count > 0:

                self.update_status(f"Seleccionadas {count} cajas")

            else:

                self.update_status("Listo - Selecciona una caja")

            return



        # Update viewer selection only when in page mode

        self.viewer.selected_pages = self.grid.selected_indices.copy()

        count = len(self.viewer.selected_pages)

        if count > 0:

            self.update_status(f"Seleccionadas {count} páginas")

        else:

            self.update_status("Listo")



    def _on_thumbnail_click(self, index: int, event):

        """Handle click on thumbnail - selection only, editor opens with E key"""

        if index == -1:

            return

        

        # In box mode: handle retry for failed boxes

        if self.grid.box_mode:

            box = self.grid.get_box_at(index)

            if box:

                if box.state == BoxState.FAILED:

                    self._retry_remote_box(box, index)

                else:

                    self.update_status(f"Caja seleccionada: {box.name}")

            return

        

        # In page mode: just update status, selection is handled by grid

        # Editor opens only with E key (open_page_editor)

        self.update_status(f"Página {index + 1} seleccionada")



    def _on_right_click(self, index: int, event):

        """Handle right click"""

        menu = Menu(self.root, tearoff=0)

        

        # Load menu icons (cached after first call)

        # Normal icons

        icons = {

            "expand": get_menu_icon("expand"),

            "edit": get_menu_icon("edit"),

            "merge": get_menu_icon("merge"),

            "retry": get_menu_icon("retry"),

            "folder": get_menu_icon("folder"),

            "file": get_menu_icon("file"),

            "save": get_menu_icon("save"),

            "upload": get_menu_icon("upload"),

            "download": get_menu_icon("download"),

            "view": get_menu_icon("view"),

            "collapse": get_menu_icon("collapse"),

            "select_all": get_menu_icon("select_all"),

            "undo": get_menu_icon("undo"),

            "redo": get_menu_icon("redo"),

            "duplicate": get_menu_icon("duplicate"),

            "blank": get_menu_icon("blank"),

            "delete": get_menu_icon("delete"),

            "rotate": get_menu_icon("rotate"),

            "mark": get_menu_icon("mark"),

            "unmark": get_menu_icon("unmark"),

            "number": get_menu_icon("number"),

            "format": get_menu_icon("format"),

            "position": get_menu_icon("position"),

            "split": get_menu_icon("split"),

            "cut": get_menu_icon("cut"),

            "index": get_menu_icon("index"),

            # Dimmed versions for disabled items

            "merge_dim": get_menu_icon("merge", dimmed=True),

            "select_all_dim": get_menu_icon("select_all", dimmed=True),

            "undo_dim": get_menu_icon("undo", dimmed=True),

            "redo_dim": get_menu_icon("redo", dimmed=True),

            "duplicate_dim": get_menu_icon("duplicate", dimmed=True),

            "blank_dim": get_menu_icon("blank", dimmed=True),

            "delete_dim": get_menu_icon("delete", dimmed=True),

            "edit_dim": get_menu_icon("edit", dimmed=True),

            "rotate_dim": get_menu_icon("rotate", dimmed=True),

            "mark_dim": get_menu_icon("mark", dimmed=True),

            "unmark_dim": get_menu_icon("unmark", dimmed=True),

            "number_dim": get_menu_icon("number", dimmed=True),

            "format_dim": get_menu_icon("format", dimmed=True),

            "position_dim": get_menu_icon("position", dimmed=True),

            "split_dim": get_menu_icon("split", dimmed=True),

            "upload_dim": get_menu_icon("upload", dimmed=True),

            "cut_dim": get_menu_icon("cut", dimmed=True),

            "save_dim": get_menu_icon("save", dimmed=True),

        }

        # Keep references to prevent garbage collection

        self._menu_icons = icons

        

        # Check if we're in box mode

        if self.grid.box_mode:

            # Box mode context menu

            has_multi_selection = len(self.grid.selected_indices) >= 2

            has_boxes = len(self.grid.document_boxes) > 0

            has_undo = bool(self.undo_stack)

            has_redo = bool(self.redo_stack)

            box = self.grid.get_box_at(index) if index is not None and index >= 0 else None

            # Nota: En menú contextual de modo cajas NO cambiamos la selección.

            # "Editar" debe actuar sobre la caja bajo el ratón (si existe) y, si no,

            # caer al comportamiento anterior: editar la caja seleccionada.

            has_box_under_mouse = box is not None

            has_box_selection = bool(self.grid.selected_indices)

            can_edit = has_box_under_mouse or has_box_selection



            def _edit_box_from_context_menu():

                """Abre el editor para la caja bajo el ratón (fallback a selección si clic en vacío)."""

                if has_box_under_mouse and index is not None and index >= 0:

                    self._on_thumbnail_double_click(index)

                    return

                self.open_page_editor()

            is_remote = isinstance(box, RemoteDocumentBox)

            can_retry = is_remote and box.state == BoxState.FAILED

            # Use box state instead of disk I/O for faster menu opening

            has_file = box and box.state == BoxState.LOADED and getattr(box, "file_path", None)



            menu.add_command(

                label="Expandir",

                accelerator="(Intro)",

                command=self.expand_all_boxes,

                image=icons["expand"],

                compound="left"

            )

            menu.add_command(

                label="Editar",

                accelerator="(E)",

                command=_edit_box_from_context_menu,

                state="normal" if can_edit else "disabled",

                image=icons["edit"] if can_edit else icons["edit_dim"],

                compound="left"

            )

            menu.add_command(

                label="Fusionar cajas seleccionadas",

                accelerator="(F)",

                command=self.merge_selected_boxes,

                state="normal" if has_multi_selection else "disabled",

                image=icons["merge"] if has_multi_selection else icons["merge_dim"],

                compound="left"

            )

            

            menu.add_separator()

            

            menu.add_command(

                label="Seleccionar todo/nada",

                accelerator="(Espacio)",

                command=self.toggle_selection,

                state="normal" if has_boxes else "disabled",

                image=icons["select_all"] if has_boxes else icons["select_all_dim"],

                compound="left"

            )

            menu.add_command(

                label="Deshacer",

                accelerator="(Ctrl + Z)",

                command=self.undo,

                state="normal" if has_undo else "disabled",

                image=icons["undo"] if has_undo else icons["undo_dim"],

                compound="left"

            )

            menu.add_command(

                label="Rehacer",

                accelerator="(Ctrl + Y)",

                command=self.redo,

                state="normal" if has_redo else "disabled",

                image=icons["redo"] if has_redo else icons["redo_dim"],

                compound="left"

            )

            if can_retry:

                menu.add_separator()

                menu.add_command(

                    label="Reintentar descarga",

                    command=lambda b=box, i=index: self._retry_remote_box(b, i),

                    image=icons["retry"],

                    compound="left"

                )

                

                # Check for Authenticated Copy to offer Normal download fallback

                doc_info = box.metadata.get("document") if box.metadata else None

                if doc_info and getattr(doc_info, "es_copia_autentica", False):

                    menu.add_command(

                         label="Reintentar como descarga normal",

                         command=lambda b=box, i=index: self._retry_remote_box(b, i, force_normal=True),

                         image=icons["download"],

                         compound="left"

                    )

            if has_file:

                # menu.add_separator()

                menu.add_command(

                    label="Abrir en Lector Externo",

                    command=lambda b=box: self._open_box_file(b),

                    image=icons["folder"],

                    compound="left"

                )

            menu.add_separator()

            menu.add_command(

                label="Abrir PDF...",

                accelerator="(Ctrl + A)",

                command=self.open_pdf,

                image=icons["file"],

                compound="left"

            )

            # Guardar en PDF justo debajo de Abrir PDF

            menu.add_command(

                label="Guardar en PDF...",

                accelerator="(Mayús + S)",

                command=self.show_save_dialog,

                state="normal" if has_boxes else "disabled",

                image=icons["save"] if has_boxes else icons["save_dim"],

                compound="left"

            )

            menu.add_separator()

            if self.extensions:

                menu.add_command(

                    label="Subir Expediente al OVE",

                    accelerator="(Ctrl + S)",

                    command=self._handle_ove_upload_shortcut,

                    state="normal" if has_boxes else "disabled",

                    image=icons["upload"] if has_boxes else icons["upload_dim"],

                    compound="left"

                )

                

                menu.add_command(

                    label="Descargar Expediente OVE",

                    accelerator="(Ctrl + O)",

                    command=self._trigger_ove_download,

                    image=icons["download"],

                    compound="left"

                )



                menu.add_command(

                    label="Descargar Expediente OVE (Avanzado)",

                    accelerator="(Mayús + O)",

                    command=self._open_ove_advanced_download_dialog,

                    image=icons["download"],

                    compound="left"

                )

            menu.add_separator()

            

            # View mode toggle

            view_mode_label = "Vista Normal (con Sidebar)" if self.grid.continuous_mode else "Vista Continua (sin Sidebar)"

            menu.add_command(

                label=view_mode_label,

                accelerator="(Alt + V)",

                command=self.toggle_continuous_mode,

                image=icons["view"],

                compound="left"

            )

            menu.tk_popup(event.x_root, event.y_root)

            # El menú ya está mostrado; en modo cajas no seguimos con el menú de miniaturas.

            return

        

        # Check if there are pages loaded

        has_pages = self.viewer.get_page_count() > 0

        has_selection = len(self.viewer.selected_pages) > 0

        has_marked = len(self.viewer.marked_pages) > 0

        has_undo = bool(self.undo_stack)

        has_redo = bool(self.redo_stack)

        # Split only allowed if exactly one page is selected and we clicked on an item

        single_selection = len(self.grid.selected_indices) == 1

        can_split = index != -1 and has_pages and single_selection

        

        # Collapse to boxes option (only if can collapse)

        if self._can_collapse_to_boxes:

            menu.add_command(

                label="Colapsar a Cajas",

                accelerator="(Retroceso)",

                command=self.collapse_to_boxes,

                image=icons["collapse"],

                compound="left"

            )

            menu.add_separator()

        

        # File operations

        menu.add_command(

            label="Abrir PDF...",

            accelerator="(Ctrl + A)",

            command=self.open_pdf,

            image=icons["file"],

            compound="left"

        )

        # Guardar en PDF justo debajo de Abrir PDF

        menu.add_command(

            label="Guardar en PDF...",

            accelerator="(Mayús + S)",

            command=self.show_save_dialog,

            state="normal" if has_pages else "disabled",

            image=icons["save"] if has_pages else icons["save_dim"],

            compound="left"

        )

        

        menu.add_separator()

        

        # Selection operations

        menu.add_command(

            label="Seleccionar todo/nada",

            accelerator="(Espacio)",

            command=self.toggle_selection,

            state="normal" if has_pages else "disabled",

            image=icons["select_all"] if has_pages else icons["select_all_dim"],

            compound="left"

        )



        menu.add_command(

            label="Deshacer",

            accelerator="(Ctrl + Z)",

            command=self.undo,

            state="normal" if has_undo else "disabled",

            image=icons["undo"] if has_undo else icons["undo_dim"],

            compound="left"

        )



        menu.add_command(

            label="Rehacer",

            accelerator="(Ctrl + Y)",

            command=self.redo,

            state="normal" if has_redo else "disabled",

            image=icons["redo"] if has_redo else icons["redo_dim"],

            compound="left"

        )



        menu.add_separator()

        

        # Page editor

        menu.add_command(

            label="Editar páginas seleccionadas",

            accelerator="(E)",

            command=self.open_page_editor,

            state="normal" if has_selection else "disabled",

            image=icons["edit"] if has_selection else icons["edit_dim"],

            compound="left"

        )

        

        # Page operations - Submenu

        page_ops_menu = Menu(menu, tearoff=0)

        

        page_ops_menu.add_command(

            label="Duplicar páginas",

            accelerator="(D)",

            command=self.duplicate_selected,

            state="normal" if has_selection else "disabled",

            image=icons["duplicate"] if has_selection else icons["duplicate_dim"],

            compound="left"

        )

        page_ops_menu.add_command(

            label="Añadir páginas en blanco",

            accelerator="(Mayúsculas + D)",

            command=self.insert_blank_pages,

            state="normal" if has_pages else "disabled",

            image=icons["blank"] if has_pages else icons["blank_dim"],

            compound="left"

        )

        page_ops_menu.add_command(

            label="Eliminar páginas",

            accelerator="(Supr)",

            command=self.delete_selected,

            state="normal" if has_selection else "disabled",

            image=icons["delete"] if has_selection else icons["delete_dim"],

            compound="left"

        )

        

        page_ops_menu.add_separator()

        

        page_ops_menu.add_command(

            label="Girar páginas hacia la derecha",

            accelerator="(Ctrl + R)",

            command=self.rotate_selected,

            state="normal" if has_selection else "disabled",

            image=icons["rotate"] if has_selection else icons["rotate_dim"],

            compound="left"

        )

        

        page_ops_menu.add_separator()

        

        page_ops_menu.add_command(

            label="Marcar páginas en blanco",

            accelerator="(B)",

            command=self.mark_selected_blank,

            state="normal" if has_selection else "disabled",

            image=icons["mark"] if has_selection else icons["mark_dim"],

            compound="left"

        )

        page_ops_menu.add_command(

            label="Desmarcar páginas",

            accelerator="(Mayúsculas + B)",

            command=self.unmark_selected,

            state="normal" if has_selection else "disabled",

            image=icons["unmark"] if has_selection else icons["unmark_dim"],

            compound="left"

        )

        page_ops_menu.add_command(

            label="Borrar páginas marcadas",

            accelerator="(X)",

            command=self.delete_marked,

            state="normal" if has_marked else "disabled",

            image=icons["delete"] if has_marked else icons["delete_dim"],

            compound="left"

        )

        

        menu.add_cascade(label="Páginas Seleccionadas", menu=page_ops_menu)

        

        menu.add_separator()

        

        # Numeración (como sección separada, no submenu)

        menu.add_command(

            label="Añadir Numeración",

            accelerator="(T)",

            command=self.add_page_numbering,

            state="normal" if has_selection else "disabled",

            image=icons["number"] if has_selection else icons["number_dim"],

            compound="left"

        )

        menu.add_command(

            label="Eliminar Numeración",

            accelerator="(Mayúsculas + T)",

            command=self.remove_page_numbering,

            state="normal" if has_selection else "disabled",

            image=icons["number"] if has_selection else icons["number_dim"],

            compound="left"

        )

        menu.add_command(

            label="Personalizar Formato Numeración...",

            command=self.customize_numbering_format,

            state="normal" if has_pages else "disabled",

            image=icons["format"] if has_pages else icons["format_dim"],

            compound="left"

        )

        menu.add_command(

            label="Cambiar Posición Numeración...",

            command=self.change_numbering_position,

            state="normal" if has_pages else "disabled",

            image=icons["position"] if has_pages else icons["position_dim"],

            compound="left"

        )

        menu.add_separator()



        # Generar Indice

        menu.add_command(

            label="Generar Indice",

            accelerator="(Ctrl + I)",

            command=self.generate_index,

            image=icons.get("index"),

            compound="left"

        )

        menu.add_separator()

        

        # Section operations (only if clicking on a valid page)

        menu.add_command(

            label="Activar/Desactivar Modo Corte",

            accelerator="(K)",

            command=self.toggle_cut_mode,

            state="normal" if has_pages else "disabled",

            image=icons["cut"] if has_pages else icons["cut_dim"],

            compound="left"

        )

        menu.add_command(

            label="Dividir Sección Aquí",

            accelerator="(Ctrl + K)",

            command=lambda: self.split_section(index),

            state="normal" if can_split else "disabled",

            image=icons["split"] if can_split else icons["split_dim"],

            compound="left"

        )

        

        

        menu.add_separator()

        

        # Zoom operations (deshabilitadas si no hay páginas)

        menu.add_command(

            label="Aumentar Zoom",

            accelerator="(Ctrl + +)",

            command=self.zoom_in,

            state="normal" if has_pages else "disabled"

        )

        menu.add_command(

            label="Reducir Zoom",

            accelerator="(Ctrl + -)",

            command=self.zoom_out,

            state="normal" if has_pages else "disabled"

        )

        menu.add_command(

            label="Zoom 100%",

            accelerator="(Ctrl + 0)",

            command=self.zoom_reset,

            state="normal" if has_pages else "disabled"

        )



        if self.extensions:

            menu.add_separator()

            menu.add_command(

                label="Subir el Expediente al OVE",

                accelerator="(Ctrl + S)",

                command=self._handle_ove_upload_shortcut,

                state="normal" if has_pages else "disabled",

                image=icons["upload"] if has_pages else icons["upload_dim"],

                compound="left"

            )

            menu.add_command(

                label="Descargar Expediente del OVE",

                accelerator="(Ctrl + O)",

                command=self._trigger_ove_download,

                image=icons["download"],

                compound="left"

            )



            menu.add_command(

                label="Descargar Expediente del OVE (Avanzado)",

                accelerator="(Mayús + O)",

                command=self._open_ove_advanced_download_dialog,

                image=icons["download"],

                compound="left"

            )



        menu.add_separator()

        

        menu.add_command(

            label="Limpiar todo (Reiniciar aplicación)",

            accelerator="(Ctrl + N)",

            command=self.clear_all

        )

        

        menu.add_separator()

        

        # View mode toggle

        view_mode_label = "Vista Normal (con Sidebar)" if self.grid.continuous_mode else "Vista Continua (sin Sidebar)"

        menu.add_command(

            label=view_mode_label,

            accelerator="(Alt + V)",

            command=self.toggle_continuous_mode,

            image=icons["view"],

            compound="left"

        )

        

        menu.tk_popup(event.x_root, event.y_root)



    def split_section(self, index: int):

        """Split section at index"""

        self.add_undo_snapshot()

        # Removed box_mode check to allow backend split

        

        # Ensure backend is ready if we are in box mode

        if self.grid.box_mode:

            self._ensure_backend_sync()



        # Get section info before split for logging

        section = self.section_manager.get_section_at(index)

        section_name = section.title if section else "desconocida"

        

        base_name = section.title if section else None

        self.section_manager.split_section(index, base_name=base_name)

        

        # Update Grid Views

        if self.grid.box_mode:

            # If in Box Mode, we must regenerate the boxes to reflect the split

            from src.pdf.structure import LocalDocumentBox, BoxState

            new_boxes = self._rebuild_boxes_from_sections(self.section_manager.sections)

            self.grid.set_box_mode(new_boxes)

            self.update_status(f"Sección '{section_name}' dividida. Cajas actualizadas.")

        else:

            self.grid.set_sections(self.section_manager.sections)

        

        log.info(f"Sección '{section_name}' dividida en página {index}")



    def _handle_split_shortcut(self, event=None):

        """Handle Ctrl+K shortcut - splits section at current selection or editor page"""

        # If editor is active, split at editor's current page

        if self.editor_active and self.current_editor:

            self._split_section_from_editor(self.current_editor.page_index)

            return



        # Not in editor: split at selection

        if len(self.grid.selected_indices) != 1:

            self.update_status("Selecciona exactamente UNA página para dividir la sección")

            return

            

        selected_index = list(self.grid.selected_indices)[0]

        # Split at the selected index

        self.split_section(selected_index)

    

    def _split_section_from_editor(self, index: int):

        """Split section at index from page editor - updates grid after split"""

        self.split_section(index)

        # Update status to confirm action

        section = self.section_manager.get_section_at(index)

        if section:

            self.update_status(f"Sección dividida en página {index + 1}: '{section.title}'")

        

        # Force refresh of editor title if active

        if self.editor_active and self.current_editor:

            # Re-calculate section name for the current page

            # Similar logic to open_page_editor_for_page or _navigate_editor_page

            section_name = ""

            if section:

                rel_page = index - section.start_page + 1

                section_name = f"{section.title} ({rel_page} de {section.page_count})"

            

            # Use internal method or show_page to update the title label

            # We call show_page with same index to force update of title

            self.current_editor.show_page(index, section_name=section_name)



    def _on_section_reorder(self, section: Section, insert_index: int):

        """Reordenar una sección arrastrándola desde el sidebar en modo miniaturas.



        Implementación:

        - Una sección es un bloque contiguo dentro de `self.viewer.pages`.

        - Reordenamos esos bloques y reconstruimos `viewer.pages`.

        - Recalculamos `start_page` para todas las secciones.

        - Remapeamos selección/marcados y limpiamos cachés del grid (las miniaturas van por índice).

        """

        # Esta acción solo tiene sentido en modo miniaturas (no en modo cajas).

        if self.grid.box_mode:

            return



        # No permitimos arrastrar secciones especiales (por ejemplo 'Borrados').

        if not section or section.is_special:

            return



        if not self.section_manager.sections:

            return



        try:

            from_idx = self.section_manager.sections.index(section)

        except ValueError:

            return



        # Si hay una sección especial al final (Borrados), impedimos insertar después.

        deleted_idx = -1

        if self.section_manager.sections and self.section_manager.sections[-1].is_special:

            deleted_idx = len(self.section_manager.sections) - 1



        max_insert = deleted_idx if deleted_idx >= 0 else len(self.section_manager.sections)

        insert_index = max(0, min(insert_index, max_insert))



        # No-op (misma posición).

        if insert_index == from_idx or insert_index == from_idx + 1:

            return



        self.add_undo_snapshot()



        # Snapshot previo para preservar selección/marcados por identidad de página.

        old_pages_snapshot = list(self.viewer.pages)

        old_selected_snapshot = set(self.viewer.selected_pages)

        old_marked_snapshot = set(self.viewer.marked_pages)



        # 1) Construir bloques actuales según offsets de sección.

        blocks = []  # List[tuple[Section, List[tuple]]]

        total_pages = len(self.viewer.pages)

        for s in self.section_manager.sections:

            start = max(0, min(s.start_page, total_pages))

            end = max(0, min(s.start_page + s.page_count, total_pages))

            page_block = self.viewer.pages[start:end]

            # Seguridad: si por algún motivo `page_count` no coincide, lo corregimos al tamaño real.

            s.page_count = len(page_block)

            blocks.append((s, page_block))



        # 2) Reordenar el bloque.

        moving = blocks.pop(from_idx)

        if from_idx < insert_index:

            insert_index -= 1

        blocks.insert(insert_index, moving)



        # 3) Reconstruir viewer.pages y offsets.

        new_pages = []

        new_sections = []

        current_start = 0

        for s, page_block in blocks:

            s.start_page = current_start

            s.page_count = len(page_block)

            current_start += s.page_count

            new_sections.append(s)

            new_pages.extend(page_block)



        self.viewer.pages = new_pages



        # 4) Remap de selección y marcados.

        new_index_by_page = {page: i for i, page in enumerate(self.viewer.pages)}



        new_selected = set()

        for old_i in old_selected_snapshot:

            if 0 <= old_i < len(old_pages_snapshot):

                page_key = old_pages_snapshot[old_i]

                if page_key in new_index_by_page:

                    new_selected.add(new_index_by_page[page_key])

        self.viewer.selected_pages = new_selected



        new_marked = set()

        for old_i in old_marked_snapshot:

            if 0 <= old_i < len(old_pages_snapshot):

                page_key = old_pages_snapshot[old_i]

                if page_key in new_index_by_page:

                    new_marked.add(new_index_by_page[page_key])

        self.viewer.marked_pages = new_marked



        # 5) Persistir secciones y refrescar grid.

        self.section_manager.sections = new_sections

        # CRÍTICO: tras reordenar `viewer.pages`, el grid debe recalcular aspect ratios/tamaños

        # porque éstos están asociados al índice (y el índice ahora apunta a otra página).

        total_pages = self.viewer.get_page_count()

        try:

            all_sizes = self.viewer.get_all_page_sizes()

        except Exception:

            all_sizes = None



        if all_sizes and len(all_sizes) == total_pages:

            self.grid.set_item_count(total_pages, page_sizes=all_sizes)

        else:

            self.grid.set_item_count(total_pages)



        # Reaplicar selección y marcados en el grid.

        self.grid.selected_indices = set(self.viewer.selected_pages)

        if hasattr(self.grid, 'marked_indices'):

            self.grid.marked_indices = set(self.viewer.marked_pages)



        self.grid.set_sections(self.section_manager.sections)

        self.update_status("Secciones reordenadas")



    def _on_section_click(self, section: Section):

        """Handle section click (Rename)"""

        if section.is_special:

            return  # Disable rename for special sections like 'Borrados'

            

        # Previous behavior was select all pages. 

        # New behavior: Open Rename Dialog directly.

        self.rename_section(section)



    def _on_section_right_click(self, section: Section, event):

        """Handle section right click"""

        menu = Menu(self.root, tearoff=0)

        

        # --- Special Handling for Deleted Section ---

        if section.is_special and section.id == "deleted":

            menu.add_command(label="Vaciar papelera", command=self.empty_trash)

            menu.tk_popup(event.x_root, event.y_root)

            return

        

        # Predefined names

        names = self.config.get_section_names()

        if names:

            for name in names:

                menu.add_command(label=name, command=lambda n=name: self.rename_section_to(section, n))

            menu.add_separator()

            

        # Standard operations

        # User requested to remove "Fusionar con anterior"

        # menu.add_command(label="Fusionar con anterior", command=lambda: self.merge_section_up(section))

        # menu.add_separator()

        

        # Split options (V1 style)

        # We must strip existing suffix to avoid double suffixes in the menu label (e.g. "merged/2M/6p")

        import re

        base_title = re.sub(r'/\d+[pPbBmMkK]$', '', section.title)

        

        # Get last used values from config

        last_pages = self.config.get_last_split_pages()

        last_mb = self.config.get_last_split_size_mb()

        

        menu.add_command(label=f"{base_title}/{last_pages}p", command=lambda: self.set_section_split_pages(section, last_pages))

        menu.add_command(label=f"{base_title}/{last_mb}M", command=lambda: self.set_section_split_size(section, last_mb * 1024 * 1024))

        

        menu.tk_popup(event.x_root, event.y_root)



    def set_section_split_pages(self, section, pages):

        """Set section to split by pages"""

        # BLINDAJE: en modo cajas no hay secciones operativas.

        if self.grid.box_mode:

            return

        try:

            idx = self.section_manager.sections.index(section)

            self.section_manager.set_split_config(idx, pages, 'p')

            self.grid.set_sections(self.section_manager.sections)

            # Save preference

            self.config.set_last_split_pages(pages)

        except ValueError:

            pass



    def set_section_split_size(self, section, size_bytes):

        """Set section to split by size"""

        # BLINDAJE: en modo cajas no hay secciones operativas.

        if self.grid.box_mode:

            return

        try:

            idx = self.section_manager.sections.index(section)

            self.section_manager.set_split_config(idx, size_bytes, 'b')

            self.grid.set_sections(self.section_manager.sections)

            

            # Save preference (convert to MB roughly, or just check if it matches M unit)

            # We assume user uses MB mostly.

            mb = size_bytes // (1024 * 1024)

            if mb > 0:

                self.config.set_last_split_size_mb(mb)

                

        except ValueError:

            pass



    def rename_section_to(self, section, new_name):

        """Rename section to specific name"""

        # BLINDAJE: en modo cajas no hay secciones operativas.

        if self.grid.box_mode:

            return

        try:

            old_name = section.title

            idx = self.section_manager.sections.index(section)

            self.section_manager.rename_section(idx, new_name)

            self.grid.set_sections(self.section_manager.sections)

            

            log.info(f"Sección renombrada: '{old_name}' → '{new_name}'")

            

            # Check if we can save a new preference from this rename

            if section.split_config:

                val, type_ = section.split_config

                if type_ == 'p':

                    self.config.set_last_split_pages(val)

                elif type_ == 'b':

                    # Check if it was MB

                    if val >= 1024*1024:

                        self.config.set_last_split_size_mb(val // (1024*1024))

                        

        except ValueError:

            pass



    def rename_section(self, section):

        """Rename section"""

        # BLINDAJE: en modo cajas no hay secciones operativas.

        if self.grid.box_mode:

            return

        dialog = CenteredInputDialog(self.root, text=f"Nuevo nombre para '{section.title}':", title="Renombrar Sección", initial_value=section.title)

        new_name = dialog.get_input()

        if new_name:

            try:

                old_name = section.title

                idx = self.section_manager.sections.index(section)

                self.section_manager.rename_section(idx, new_name)

                self.grid.set_sections(self.section_manager.sections)

                log.info(f"Sección renombrada: '{old_name}' → '{new_name}'")

            except ValueError:

                pass

    

    def _refresh_sidebar_after_dialog(self):

        """Actualiza el sidebar después de cerrar SaveDialog para reflejar cambios de autonumeración"""

        # BLINDAJE: en modo cajas no hay secciones que refrescar (el diálogo solo
        # muta wrappers SimpleNamespace). Reinyectar secciones aquí corrompe el
        # layout y el sidebar ("secciones fantasma" tras Guardar como PDF).
        if self.grid.box_mode:

            return

        # En modo visor, actualizar las secciones en el grid

        if self.viewer and self.viewer.documents:

            self.grid.set_sections(self.section_manager.sections)



    def rename_box(self, index: int):

        """Rename box (and underlying section/file)"""

        box = self.grid.get_box_at(index)

        if not box:

            return

            

        dialog = CenteredInputDialog(

            self.root, 

            text=f"Nuevo nombre para '{box.name}':", 

            title="Renombrar Caja", 

            initial_value=box.name

        )

        new_name = dialog.get_input()

        

        if new_name and new_name != box.name:

            self.add_undo_snapshot()

            box.name = new_name

            self.grid.update_box_state(index)

            

            # If this box corresponds to a section (merged box), we should rename the section too

            # But we are in box mode, so sections might not be active/valid in the same way.

            # However, when we expand, we want the section to have this name.

            # We store the name in the box, and when expanding, we use it.

            

            # If it's a RemoteDocumentBox, we just update the name.

            # If it's a LocalDocumentBox (from collapse), we should update the section title if possible.

            

            if hasattr(box, 'metadata') and box.metadata.get('section_index') is not None:

                # It was collapsed from a section

                s_idx = box.metadata['section_index']

                if 0 <= s_idx < len(self.section_manager.sections):

                    self.section_manager.rename_section(s_idx, new_name)

            

            log.info(f"Caja renombrada: '{box.name}' → '{new_name}'")



    def _on_box_right_click(self, index: int, event):

        """Manejar clic derecho en el área del nombre de una caja - mostrar menú de nombres predefinidos"""

        box = self.grid.get_box_at(index)

        if not box:

            return

        

        # Crear menú contextual con nombres predefinidos

        menu = Menu(self.root, tearoff=0)

        

        # Obtener nombres predefinidos de la configuración

        names = self.config.get_section_names()

        if names:

            for name in names:

                menu.add_command(label=name, command=lambda n=name, idx=index: self._rename_box_to(idx, n))

            menu.add_separator()

        

        # Opción para renombrar manualmente (abre el diálogo de input)

        menu.add_command(label="Renombrar...", command=lambda: self.rename_box(index))

        

        # Mostrar menú en la posición del cursor

        menu.tk_popup(event.x_root, event.y_root)

    

    def _rename_box_to(self, index: int, new_name: str):

        """Renombrar caja a un nombre específico (desde menú contextual)"""

        box = self.grid.get_box_at(index)

        if not box:

            return

        

        if new_name and new_name != box.name:

            self.add_undo_snapshot()

            box.name = new_name

            self.grid.update_box_state(index)

            

            # Si la caja corresponde a una sección (caja fusionada), renombrar la sección también

            if hasattr(box, 'metadata') and box.metadata.get('section_index') is not None:

                s_idx = box.metadata['section_index']

                if 0 <= s_idx < len(self.section_manager.sections):

                    self.section_manager.rename_section(s_idx, new_name)

            

            log.info(f"Caja renombrada: '{box.name}' → '{new_name}'")



    def merge_section_up(self, section):

        """Merge section with previous"""

        self.add_undo_snapshot()

        try:

            idx = self.section_manager.sections.index(section)

            if idx > 0:

                prev_section = self.section_manager.sections[idx - 1]

                self.section_manager.merge_section_up(idx)

                self.grid.set_sections(self.section_manager.sections)

                log.info(f"Sección '{section.title}' fusionada con '{prev_section.title}'")

        except ValueError:

            pass



    def toggle_cut_mode(self, event=None):

        """Toggle cut mode (scissors)"""

        if self.grid.box_mode:

            self.update_status("No puedes cortar mientras estés en modo cajas. Expande primero.")

            return



        if self.editor_active:

             return



        if self.viewer.get_page_count() == 0:

            return



        self.cut_mode = not self.cut_mode

        self.grid.cut_mode = self.cut_mode

        self.grid.redraw() # Force visual update

        

        self.update_status("Modo CORTE activado (Click entre páginas para dividir)" if self.cut_mode else "Modo CORTE desactivado")



        

    def toggle_continuous_mode(self, event=None):

        """Toggle Continuous View Mode"""

        # Toggle state in grid

        new_state = not self.grid.continuous_mode

        self._set_continuous_mode(new_state)

        

    def _set_continuous_mode(self, enabled: bool):

        """Set continuous view mode and persist"""

        self.grid.set_continuous_mode(enabled)

        self.config.set_continuous_mode(enabled)

        

        # Show/Hide sidebar

        if enabled:

            self.grid.sidebar.grid_remove() # Hide sidebar

            self.update_status("Modo Miniaturas Continuo ACTIVADO (Sidebar oculto)")

        else:

            self.grid.sidebar.grid() # Show sidebar

            self.update_status("Modo Miniaturas Continuo DESACTIVADO")

            

    def deactivate_cut_mode(self, event=None):

        """Deactivate cut mode and keyboard move mode (ESC key)"""

        # Cancelar modo movimiento con teclado si está activo

        if self.grid.keyboard_move_mode:

            self.grid.cancel_keyboard_move()

            self.update_status("Movimiento cancelado")

            return

        

        # Desactivar modo corte

        if self.cut_mode:

            self.cut_mode = False

            self.grid.cut_mode = False

            self.grid.redraw()

            self.update_status("Listo")

            self.root.configure(cursor="")

            

    def split_section_at(self, index: int):

        """Callback from grid to split section"""

        if self.grid.box_mode:

            return



        # Split BEFORE index (between index-1 and index)

        # If index is 0, can't split before.

        if index <= 0:

            return

            

        # Find which section contains this index

        # We want to split at index, meaning index starts a new section

        

        # Check if already split (if index is start of a section)

        for s in self.section_manager.sections:

            if s.start_page == index:

                self.update_status(f"Ya existe un corte en la página {index}")

                return



        self.split_section(index)

        self.update_status(f"Sección dividida en página {index}")







    def extract_selection_to_file(self, event=None):

        """Extract selected pages to new file (Cut)"""

        selected = sorted(list(self.grid.selected_indices))

        if not selected:

            return

            

        with self._preserve_cwd():

            filename = filedialog.asksaveasfilename(

                title="Guardar páginas cortadas como PDF...",

                defaultextension=".pdf",

                filetypes=[("PDF files", "*.pdf")]

            )

        if not filename:

            return

            

        try:

            # Save selection to new file

            self.viewer.doc.save_subset(filename, selected)

            

            # Delete from current doc

            # We must delete from end to start to avoid shifting indices

            # But viewer.delete_pages might handle list? 

            # Let's check PdfViewer. It probably doesn't have delete_pages for list yet.

            # But PdfDocument has delete_page(int).

            

            # Deleting multiple pages is tricky because indices shift.

            # We should sort descending.

            for page_num in sorted(selected, reverse=True):

                self.viewer.delete_page(page_num)

                

            # Update structure

            # This invalidates all sections. We should ideally re-calculate or update.

            # For now, re-init default section to avoid inconsistency or try to keep if simple.

            # But cutting pages might empty sections.

            

            # Simple approach: Re-initialize default section with new count

            # Better approach: Update SectionManager to handle deletion.

            

            # Let's just reset sections for safety in this iteration, or update page counts if possible.

            # The user asked for "Cut", which implies removal.

            

            self.section_manager.initialize_default(self.viewer.get_page_count(), base_name=self.config.get_default_base_name())

            self.grid.set_item_count(self.viewer.get_page_count())

            self.grid.set_sections(self.section_manager.sections)

            self.grid.selected_indices.clear()

            self.grid.redraw()

            

            self.update_status(f"Cortadas {len(selected)} páginas a {Path(filename).name}")

            

        except Exception as e:

            log.error(f"Error extracting pages: {e}", exc_info=True)

            messagebox.showerror("Error", f"Error al cortar páginas:\n{e}")



    def show_save_dialog(self, event=None, initial_dir_override: Optional[str] = None):

        """Show advanced save dialog"""

        # Ignore if user is typing in an entry/text widget

        focused = self.root.focus_get()

        if isinstance(focused, (tk.Entry, tk.Text, ctk.CTkEntry, ctk.CTkTextbox)):

            return



        # Check pagination reminder - only ask if numbering has NOT been applied

        if self.config.get_check_pagination():

            # Check if numbering has been applied

            numbering_was_applied = getattr(self, 'numbering_applied', False)

            

            if not numbering_was_applied:

                # Numbering was NOT applied, so ask the user

                if not messagebox.askyesno(

                    "Advertencia de Foliado", 

                    "¿Foliaste el documento?\n\n(No se detectó numeración aplicada con la tecla T)", 

                    icon='warning'

                ):

                    return





            

        # Priority: Use directory from first loaded document (for easy overwrite)

        # This allows the common workflow: load file -> edit -> save (overwrite)

        initial_dir = None

        if hasattr(self, 'viewer') and self.viewer.documents:

            first_doc = self.viewer.documents[0]

            if hasattr(first_doc, 'filepath') and first_doc.filepath:

                doc_dir = str(first_doc.filepath.parent)

                # Bypass: Excluir rutas temporales de OVE (podofilo_ove_downloads) y de la impresora virtual (oviscapto)

                # para evitar que aparezcan como directorio inicial de guardado

                if Path(doc_dir).exists() and "podofilo_ove_downloads" not in doc_dir and "oviscapto" not in doc_dir:

                    initial_dir = doc_dir

        

        # Fallback to override or last save directory

        if not initial_dir:

            initial_dir = initial_dir_override or self.config.get_last_save_dir()

        

        # Final fallback to last loaded dir

        if not Path(initial_dir).exists():

            initial_dir = self.config.get_last_loaded_dir()

        

        # --- BOX MODE HANDLING ---

        if self.grid.box_mode:

            from types import SimpleNamespace

            

            boxes_to_save = []

            # Prefer selected boxes

            selected_indices = sorted(list(self.grid.selected_indices)) if hasattr(self.grid, 'selected_indices') else []

            if selected_indices:

                boxes_to_save = [self.grid.document_boxes[i] for i in selected_indices if i < len(self.grid.document_boxes)]

            else:

                boxes_to_save = self.grid.document_boxes

                

            # Filter valid boxes - include boxes with page_refs OR valid file_path

            # Boxes from collapsed sections have page_refs but may not have file_path

            # NOTA: Después de refactorización, usamos page_refs en lugar de pages

            valid_boxes = [b for b in boxes_to_save if 

                          (hasattr(b, 'page_refs') and b.page_refs) or 

                          (b.file_path and Path(b.file_path).exists())]

            

            if not valid_boxes:

                messagebox.showinfo("Info", "No hay cajas con archivos válidos para guardar")

                return

                

            # Wrap boxes to look like Sections for the dialog

            wrapped_sections = []

            for box in valid_boxes:

                # Approximate page count if not available (usar page_refs)

                p_count = len(box.page_refs) if hasattr(box, 'page_refs') and box.page_refs else 0

                

                # Create a fake section object

                s = SimpleNamespace()

                # Always use box.name (includes custom names and merged names)

                s.title = box.name

                s.page_count = p_count

                s.start_page = 0 # Not relevant for box copy

                s.end_page = 0   # Not relevant for box copy

                s.original_box = box # Reference for saver

                s.split_config = None # No split support in box mode

                wrapped_sections.append(s)

            

            # Obtener valores de split de la configuración

            split_pages = self.config.get_last_split_pages()

            split_mb = self.config.get_last_split_size_mb()

            dialog = SaveDialog(self.root, wrapped_sections, initial_dir, self._save_boxes, split_pages, split_mb)

            # Actualizar sidebar cuando el diálogo se cierre (para reflejar cambios de autonumeración)

            dialog.bind("<Destroy>", lambda e: self._refresh_sidebar_after_dialog())

            return

            

        # --- VIEWER MODE HANDLING ---

        # Only show saveable sections (exclude 'Borrados')

        saveable_sections = self.section_manager.get_saveable_sections()

        if not saveable_sections:

            messagebox.showinfo("Info", "No hay secciones para guardar")

            return

        

        # Obtener valores de split de la configuración

        split_pages = self.config.get_last_split_pages()

        split_mb = self.config.get_last_split_size_mb()

        dialog = SaveDialog(self.root, saveable_sections, initial_dir, self._save_sections, split_pages, split_mb)

        # Actualizar sidebar cuando el diálogo se cierre (para reflejar cambios de autonumeración)

        dialog.bind("<Destroy>", lambda e: self._refresh_sidebar_after_dialog())



    def _save_sections(self, target_dir: str, to_save: List[dict], combined_filename: str = None):

        """Callback from SaveDialog - Guarda archivos de forma asíncrona con progreso

        

        Args:

            target_dir: Directory to save files

            to_save: List of sections to save

            combined_filename: If provided, create a combined PDF with all sections

        """

        import os

        import re

        import tempfile

        

        target_path = Path(target_dir)

        

        # Persistir último directorio de guardado

        try:

            self.config.set_last_save_dir(target_dir)

        except Exception:

            pass



        # Obtener opción de eliminar firmas

        remove_signatures = False

        try:

            remove_signatures = bool(self.config.get_remove_signatures_on_save())

        except Exception:

            remove_signatures = False

        

        # Crear directorio si no existe

        target_path.mkdir(parents=True, exist_ok=True)

        

        planned_outputs: List[tuple[Path, List[int]]] = []



        def plan_output(path: Path, pages_subset: List[int]):

            planned_outputs.append((path, list(pages_subset)))



        # Planificar todos los archivos a guardar (fase síncrona rápida)

        try:

            for item in to_save:

                section = item["section"]

                filename = item["filename"]

                log.debug(f"[SAVE] Procesando sección: title='{section.title}', filename='{filename}', split_config={section.split_config}")

                if not filename.lower().endswith(".pdf"):

                    filename += ".pdf"

                

                stem = filename[:-4]

                split_config = section.split_config

                

                match = re.search(r'/(\d+)([pPbBmMkK])$', stem)

                if match:

                    val = int(match.group(1))

                    unit = match.group(2).lower()

                    log.debug(f"[SAVE] Detectado modificador en filename: val={val}, unit={unit}")

                    

                    if unit == 'p':

                        split_config = (val, 'p')

                    elif unit == 'm':

                        split_config = (val * 1024 * 1024, 'b')

                    elif unit == 'k':

                        split_config = (val * 1024, 'b')

                    elif unit == 'b':

                        split_config = (val, 'b')

                        

                    stem = re.sub(r'/\d+[pPbBmMkK]$', '', stem)

                    log.debug(f"[SAVE] split_config final: {split_config}, stem limpio: '{stem}'")

                    

                    if unit == 'p':

                        self.config.set_last_split_pages(val)

                    elif unit in ('m', 'k', 'b'):

                        mb_val = 0

                        if unit == 'm': mb_val = val

                        elif unit == 'k': mb_val = val // 1024

                        elif unit == 'b': mb_val = val // (1024*1024)

                        if mb_val > 0:

                            self.config.set_last_split_size_mb(mb_val)

                

                base_output_name = target_path / stem

                pages = list(range(section.start_page, section.end_page))

                log.debug(f"[SAVE] pages={pages}, split_config={split_config}")

                

                if split_config:

                    val, type_ = split_config

                    

                    if type_ == 'p':

                        chunk_size = int(val)

                        chunks = [pages[i:i + chunk_size] for i in range(0, len(pages), chunk_size)]

                        

                        if len(chunks) == 1:

                            output_path = target_path / f"{stem}.pdf"

                            plan_output(output_path, chunks[0])

                        else:

                            for i, chunk in enumerate(chunks):

                                start_index = i * chunk_size

                                start_rel = start_index + 1

                                end_rel = start_index + len(chunk)

                                part_filename = f"{stem}_p{start_rel}-p{end_rel}.pdf"

                                part_path = target_path / part_filename

                                plan_output(part_path, chunk)

                            

                    elif type_ == 'b':

                        limit_bytes = int(val)

                        collected_chunks = []

                        current_chunk = []

                        current_start_idx = 0

                        

                        i = 0

                        while i < len(pages):

                            current_chunk.append(pages[i])

                            

                            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:

                                tmp_path = tmp.name

                            

                            try:

                                self.viewer.save_subset(tmp_path, current_chunk, silent=True, remove_signatures=remove_signatures)

                                size = os.path.getsize(tmp_path)

                                

                                if size > limit_bytes and len(current_chunk) > 1:

                                    current_chunk.pop()

                                    i -= 1

                                    

                                    collected_chunks.append({

                                        'pages': list(current_chunk),

                                        'start': current_start_idx + 1,

                                        'end': current_start_idx + len(current_chunk)

                                    })

                                    

                                    current_chunk = []

                                    current_start_idx = i + 1

                                    

                                elif size > limit_bytes and len(current_chunk) == 1:

                                    collected_chunks.append({

                                        'pages': list(current_chunk),

                                        'start': current_start_idx + 1,

                                        'end': current_start_idx + 1

                                    })

                                    

                                    current_chunk = []

                                    current_start_idx = i + 1

                                    

                            finally:

                                if os.path.exists(tmp_path):

                                    try:

                                        os.unlink(tmp_path)

                                    except:

                                        pass

                            

                            i += 1

                            

                        if current_chunk:

                            collected_chunks.append({

                                'pages': list(current_chunk),

                                'start': current_start_idx + 1,

                                'end': current_start_idx + len(current_chunk)

                            })

                            

                        if len(collected_chunks) == 1:

                            output_path = target_path / f"{stem}.pdf"

                            plan_output(output_path, collected_chunks[0]['pages'])

                        else:

                            for chunk_info in collected_chunks:

                                start_rel = chunk_info['start']

                                end_rel = chunk_info['end']

                                part_filename = f"{stem}_p{start_rel}-p{end_rel}.pdf"

                                part_path = target_path / part_filename

                                plan_output(part_path, chunk_info['pages'])

                            

                else:

                    output_path = target_path / filename

                    plan_output(output_path, pages)



            log.debug(f"[SAVE] Total planned_outputs: {len(planned_outputs)}")

            for idx, (path, pages) in enumerate(planned_outputs):

                log.debug(f"[SAVE]   [{idx}] {path.name} -> {len(pages)} páginas")

            

            if not planned_outputs:

                log.info("No hay documentos para guardar")

                return



            # Verificar colisiones (síncrono, rápido)

            collisions = [entry for entry in planned_outputs if entry[0].exists()]

            if collisions:

                max_preview = 15

                lines = "\n".join(entry[0].name for entry in collisions[:max_preview])

                remaining = len(collisions) - max_preview

                if remaining > 0:

                    lines += f"\n... y {remaining} archivo(s) más"

                msg = (

                    "Los siguientes archivos ya existen y serán sobrescritos:\n\n"

                    f"{lines}\n\n¿Deseas continuar?"

                )

                if not messagebox.askyesno("Sobrescribir archivos", msg):

                    log.info("Operación cancelada por el usuario")

                    return



            # Añadir archivo combinado si se solicitó

            combined_path = None

            all_pages_combined = []

            if combined_filename:

                for item in to_save:

                    section = item["section"]

                    pages = list(range(section.start_page, section.end_page))

                    all_pages_combined.extend(pages)

                

                if all_pages_combined:

                    if not combined_filename.lower().endswith(".pdf"):

                        combined_filename += ".pdf"

                    

                    combined_path = target_path / combined_filename

                    

                    if combined_path.exists():

                        if not messagebox.askyesno(

                            "Sobrescribir archivo",

                            f"El archivo '{combined_filename}' ya existe.\n¿Deseas sobrescribirlo?"

                        ):

                            combined_path = None

                            all_pages_combined = []



        except Exception as e:

            log.error(f"Error planning save: {e}", exc_info=True)

            messagebox.showerror("Error", f"Error al planificar guardado:\n{e}")

            return



        # Calcular total de archivos a guardar

        total_files = len(planned_outputs) + (1 if combined_path else 0)

        

        if total_files == 0:

            return

        

        # Función de guardado asíncrono

        def save_task(progress_dialog):

            """Tarea de guardado que se ejecuta en hilo separado"""

            saved_count = 0

            errors = []

            

            try:

                # Guardar archivos individuales

                for idx, (output_path, pages_subset) in enumerate(planned_outputs):

                    if progress_dialog.is_cancelled:

                        log.info("Guardado cancelado por el usuario")

                        break

                    

                    try:

                        output_path.parent.mkdir(parents=True, exist_ok=True)

                        

                        progress_dialog.update_progress(

                            idx / total_files,

                            f"Guardando: {output_path.name}"

                        )

                        

                        # Safe Save Strategy: Save to temp file first, then replace

                        temp_output = output_path.with_suffix(output_path.suffix + ".tmp")

                        self.viewer.save_subset(str(temp_output), pages_subset, remove_signatures=remove_signatures)

                        

                        # Verify save success

                        if temp_output.exists() and temp_output.stat().st_size > 0:

                            if output_path.exists():

                                try:

                                    output_path.unlink()

                                except PermissionError as e:

                                    # El destino está abierto por otro visor: es esperado, lo logueamos

                                    # como warning (no es error fatal: el move de abajo puede aún

                                    # reemplazarlo en Windows según el tipo de lock).

                                    log_fs_error(log, e, "unlink_target",

                                                 src=output_path, level=logging.WARNING)

                            

                            # Atomic replace (or as atomic as Windows allows)

                            try:

                                import shutil

                                shutil.move(str(temp_output), str(output_path))

                            except Exception as e:

                                # El replace atómico falló. Logueamos la ruta del .tmp huérfano

                                # para poder recuperarlo manualmente, y propagamos el error.

                                log_fs_error(log, e, "atomic_replace",

                                             src=temp_output, dst=output_path)

                                raise

                        else:

                            raise Exception("Temporary file creation failed")



                        saved_count += 1

                        log.info(f"✓ Guardado: {output_path.name}")

                        

                    except Exception as e:

                        if 'temp_output' in locals() and temp_output.exists():

                            try:

                                temp_output.unlink()

                            except: pass

                        

                        # Intento de diagnóstico si parece un error de estructura

                        err_str = str(e).lower()

                        culprit = None

                        if "cycle" in err_str or "structure" in err_str or "code=7" in err_str:

                            log.info(f"Detectado error estructural en {output_path.name}, diagnosticando...")

                            progress_dialog.update_progress(idx / total_files, f"Diagnosticando error en {output_path.name}...")

                            culprit = self.viewer.diagnose_save_error(pages_subset, remove_signatures=remove_signatures)

                        

                        if culprit:

                            error_msg = f"Error en {output_path.name}: El archivo original '{Path(culprit).name}' está corrupto (cycle/structure error)."

                            errors.append(error_msg)

                            log.error(f"Save error diagnosed: {error_msg}")

                        else:

                            errors.append(f"{output_path.name}: {e}")

                            log.error(f"Error guardando {output_path.name}: {e}")

                

                # Guardar archivo combinado

                if combined_path and all_pages_combined and not progress_dialog.is_cancelled:

                    try:

                        progress_dialog.update_progress(

                            (len(planned_outputs)) / total_files,

                            f"Guardando combinado: {combined_path.name}"

                        )

                        

                        # Safe Save Strategy for Combined File

                        temp_combined = combined_path.with_suffix(combined_path.suffix + ".tmp")

                        self.viewer.save_subset(str(temp_combined), all_pages_combined, remove_signatures=remove_signatures)

                        

                        if temp_combined.exists() and temp_combined.stat().st_size > 0:

                             if combined_path.exists():

                                 try:

                                     combined_path.unlink()

                                 except PermissionError:

                                     pass

                             

                             import shutil

                             shutil.move(str(temp_combined), str(combined_path))

                        else:

                             raise Exception("Temporary combined file creation failed")

                        saved_count += 1

                        log.info(f"✓ Archivo combinado: {combined_path.name} ({len(all_pages_combined)} páginas)")

                        

                    except Exception as e:

                        # Intento de diagnóstico para combinado

                        err_str = str(e).lower()

                        culprit = None

                        if "cycle" in err_str or "structure" in err_str or "code=7" in err_str:

                            log.info(f"Detectado error estructural en combinado, diagnosticando...")

                            progress_dialog.update_progress(0.95, f"Diagnosticando error en combinado...")

                            culprit = self.viewer.diagnose_save_error(all_pages_combined, remove_signatures=remove_signatures)

                        

                        if culprit:

                            error_msg = f"Error en combinado: El archivo original '{Path(culprit).name}' está corrupto (cycle/structure error)."

                            errors.append(error_msg)

                            log.error(f"Save error diagnosed: {error_msg}")

                        else:

                            errors.append(f"{combined_path.name}: {e}")

                        log.error(f"Error guardando combinado: {e}")

                

                progress_dialog.update_progress(1.0, "Completado")

                

            except Exception as e:

                errors.append(str(e))

                log.error(f"Error en guardado: {e}", exc_info=True)

            

            return {"saved": saved_count, "errors": errors, "cancelled": progress_dialog.is_cancelled}

        

        # Mostrar diálogo de progreso y ejecutar guardado

        dialog = ProgressDialog(

            self.root,

            "Guardando PDFs",

            f"Guardando {total_files} archivo(s)...",

            task=save_task,

        )

        

        try:

            result = dialog.run_and_wait()

            

            if result:

                if result.get("cancelled"):

                    self.update_status(f"Guardado cancelado ({result['saved']} archivos guardados)")

                    messagebox.showinfo("Cancelado", 

                        f"Operación cancelada.\n{result['saved']} archivo(s) guardados antes de cancelar.")

                elif result.get("errors"):

                    error_msg = "\n".join(result["errors"][:5])

                    if len(result["errors"]) > 5:

                        error_msg += f"\n... y {len(result['errors']) - 5} error(es) más"

                    messagebox.showwarning("Guardado con errores",

                        f"Se guardaron {result['saved']} archivo(s).\n\nErrores:\n{error_msg}")

                    self.update_status(f"Guardado con errores: {result['saved']} de {total_files}")

                else:

                    log.info(f"✓ Guardado completado: {result['saved']} archivo(s) en {target_path}")

                    self.update_status(f"✓ Guardados {result['saved']} archivo(s)")

                    

        except Exception as e:

            log.error(f"Error saving sections: {e}", exc_info=True)

            messagebox.showerror("Error", f"Error al guardar:\n{e}")



    def _save_boxes(self, target_dir: str, to_save: List[dict], combined_filename: str = None):

        """Callback from SaveDialog when in BOX MODE - Creates PDFs from pages (like _save_sections)"""

        import shutil

        import fitz

        import threading

        

        target_path = Path(target_dir)

        

        # Persistir último directorio de guardado

        try:

            self.config.set_last_save_dir(target_dir)

        except Exception:

            pass



        # Obtener opción de eliminar firmas

        remove_signatures = False

        try:

            remove_signatures = bool(self.config.get_remove_signatures_on_save())

        except Exception:

            remove_signatures = False

        

        target_path.mkdir(parents=True, exist_ok=True)

        

        self.update_status("Guardando archivos...")

        

        # Capturar combined_filename en variable local para el closure

        combined_name = combined_filename

        

        def save_worker():

            import re

            try:

                # 1. Individual saves

                saved_files = []

                for item in to_save:

                    box_wrapper = item["section"] # It's actually a wrapper around the Box

                    box = box_wrapper.original_box

                    

                    filename = item["filename"]

                    

                    if not filename.lower().endswith(".pdf"):

                        filename += ".pdf"

                    

                    # Procesar modificadores de split (/6p, /5M, etc.) igual que en _save_sections

                    stem = filename[:-4]  # Quitar .pdf

                    split_config = None

                    

                    match = re.search(r'/(\d+)([pPbBmMkK])$', stem)

                    if match:

                        val = int(match.group(1))

                        unit = match.group(2).lower()

                        

                        if unit == 'p':

                            split_config = (val, 'p')

                        elif unit == 'm':

                            split_config = (val * 1024 * 1024, 'b')

                        elif unit == 'k':

                            split_config = (val * 1024, 'b')

                        elif unit == 'b':

                            split_config = (val, 'b')

                        

                        # Limpiar el stem quitando el modificador

                        stem = re.sub(r'/\d+[pPbBmMkK]$', '', stem)

                        

                        # Persistir configuración de split

                        if unit == 'p':

                            self.config.set_last_split_pages(val)

                        elif unit in ('m', 'k', 'b'):

                            mb_val = 0

                            if unit == 'm': mb_val = val

                            elif unit == 'k': mb_val = val // 1024

                            elif unit == 'b': mb_val = val // (1024*1024)

                            if mb_val > 0:

                                self.config.set_last_split_size_mb(mb_val)

                    

                    # Reconstruir filename limpio (sin modificador de split)

                    clean_filename = stem + ".pdf"

                    dest_path = target_path / clean_filename

                    

                    try:

                        # Priority: Check if this is a merged box with file paths

                        # Merged boxes need to be loaded from their source files

                        if hasattr(box, 'metadata') and box.metadata.get('merged_file_paths'):

                            # Merged box - load from all source files

                            merged_paths = box.metadata['merged_file_paths']

                            new_doc = fitz.open()

                            open_src_docs = []

                            for file_path in merged_paths:

                                try:

                                    src_doc = fitz.open(file_path)

                                    open_src_docs.append(src_doc)

                                    new_doc.insert_pdf(src_doc)

                                except Exception as e:

                                    log.error(f"Error loading merged file {file_path}: {e}")

                            

                            # Eliminar firmas si está activado

                            if remove_signatures and new_doc.page_count > 0:

                                for page in new_doc:

                                    for widget in page.widgets():

                                        if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:

                                            page.delete_widget(widget)

                            

                            if new_doc.page_count > 0:

                                tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

                                new_doc.save(tmp_path)

                                new_doc.close()

                                for src_doc in open_src_docs:

                                    try:

                                        src_doc.close()

                                    except Exception:

                                        pass

                                if dest_path.exists():

                                    try: dest_path.unlink()

                                    except: pass

                                import shutil

                                shutil.move(str(tmp_path), str(dest_path))

                                saved_files.append(dest_path)

                        # NUEVO: Verificar si tiene PageReference (método preferido después de refactorización)

                        elif hasattr(box, 'page_refs') and box.page_refs and len(box.page_refs) > 0:

                            from src.pdf.structure import PageReference

                            first_ref = box.page_refs[0]

                            

                            # Función helper para guardar un subconjunto de páginas

                            def save_page_subset(refs_subset, output_path):

                                """Guarda un subconjunto de PageReference a un archivo PDF"""

                                new_doc = fitz.open()

                                open_src_docs = []

                                for ref in refs_subset:

                                    if isinstance(ref, PageReference) and Path(ref.file_path).exists():

                                        try:

                                            src_doc = fitz.open(ref.file_path)

                                            open_src_docs.append(src_doc)

                                            new_doc.insert_pdf(src_doc, from_page=ref.page_index, to_page=ref.page_index)

                                        except Exception as e:

                                            log.error(f"Error loading page from {ref.file_path}:{ref.page_index}: {e}")

                                

                                # Eliminar firmas si está activado

                                if remove_signatures and new_doc.page_count > 0:

                                    for page in new_doc:

                                        for widget in page.widgets():

                                            if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:

                                                page.delete_widget(widget)

                                

                                page_count = new_doc.page_count

                                if page_count > 0:

                                    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

                                    new_doc.save(tmp_path)

                                    new_doc.close()

                                    for src_doc in open_src_docs:

                                        try:

                                            src_doc.close()

                                        except Exception:

                                            pass

                                    if output_path.exists():

                                        try: output_path.unlink()

                                        except: pass

                                    import shutil

                                    shutil.move(str(tmp_path), str(output_path))

                                    saved_files.append(output_path)

                                else:

                                    new_doc.close()

                                    for src_doc in open_src_docs:

                                        try:

                                            src_doc.close()

                                        except Exception:

                                            pass

                                return page_count

                            

                            if isinstance(first_ref, PageReference):

                                all_refs = [r for r in box.page_refs if isinstance(r, PageReference)]

                                

                                # Si hay split_config, dividir el archivo

                                if split_config:

                                    val, type_ = split_config

                                    

                                    if type_ == 'p':

                                        # Split por número de páginas

                                        chunk_size = int(val)

                                        for i in range(0, len(all_refs), chunk_size):

                                            try:

                                                chunk = all_refs[i:i + chunk_size]

                                                start_rel = i + 1

                                                end_rel = i + len(chunk)

                                                part_filename = f"{stem}_p{start_rel}-p{end_rel}.pdf"

                                                part_path = target_path / part_filename

                                                save_page_subset(chunk, part_path)

                                            except Exception as chunk_err:

                                                log.error(f"Error guardando chunk de {box.name}: {chunk_err}")

                                    

                                    elif type_ == 'b':

                                        # Split por tamaño en bytes

                                        import tempfile

                                        import os

                                        limit_bytes = int(val)

                                        current_chunk = []

                                        current_start_idx = 0

                                        

                                        i = 0

                                        while i < len(all_refs):

                                            current_chunk.append(all_refs[i])

                                            

                                            # Crear PDF temporal para medir tamaño

                                            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:

                                                tmp_test_path = tmp.name

                                            

                                            try:

                                                test_doc = fitz.open()

                                                test_open_src_docs = []

                                                for ref in current_chunk:

                                                    if Path(ref.file_path).exists():

                                                        src_doc = fitz.open(ref.file_path)

                                                        test_open_src_docs.append(src_doc)

                                                        test_doc.insert_pdf(src_doc, from_page=ref.page_index, to_page=ref.page_index)

                                                test_doc.save(tmp_test_path)

                                                test_doc.close()

                                                for src_doc in test_open_src_docs:

                                                    try:

                                                        src_doc.close()

                                                    except Exception:

                                                        pass

                                                size = os.path.getsize(tmp_test_path)

                                                

                                                if size > limit_bytes and len(current_chunk) > 1:

                                                    # Excede límite, guardar sin la última página

                                                    current_chunk.pop()

                                                    i -= 1

                                                    

                                                    start_rel = current_start_idx + 1

                                                    end_rel = start_rel + len(current_chunk) - 1

                                                    part_filename = f"{stem}_p{start_rel}-p{end_rel}.pdf"

                                                    part_path = target_path / part_filename

                                                    save_page_subset(current_chunk, part_path)

                                                    

                                                    current_chunk = []

                                                    current_start_idx = i + 1

                                                

                                                elif size > limit_bytes and len(current_chunk) == 1:

                                                    # Una sola página excede el límite, guardarla igual

                                                    start_rel = current_start_idx + 1

                                                    part_filename = f"{stem}_p{start_rel}-p{start_rel}.pdf"

                                                    part_path = target_path / part_filename

                                                    save_page_subset(current_chunk, part_path)

                                                    

                                                    current_chunk = []

                                                    current_start_idx = i + 1

                                            finally:

                                                if os.path.exists(tmp_test_path):

                                                    try: os.unlink(tmp_test_path)

                                                    except: pass

                                            

                                            i += 1

                                        

                                        # Guardar chunk restante

                                        if current_chunk:

                                            start_rel = current_start_idx + 1

                                            end_rel = start_rel + len(current_chunk) - 1

                                            part_filename = f"{stem}_p{start_rel}-p{end_rel}.pdf"

                                            part_path = target_path / part_filename

                                            save_page_subset(current_chunk, part_path)

                                else:

                                    # Sin split, guardar todo en un archivo

                                    save_page_subset(all_refs, dest_path)

                            

                            # LEGACY: Tuplas (doc_index, page_index) - mantener compatibilidad

                            elif isinstance(first_ref, tuple) and len(first_ref) == 2:

                                new_doc = fitz.open()

                                open_src_docs = []

                                for page in box.page_refs:

                                    if isinstance(page, tuple) and len(page) == 2:

                                        doc_idx, page_idx = page

                                        doc = self.viewer.documents[doc_idx]

                                        src_doc = fitz.open(doc.filepath)

                                        open_src_docs.append(src_doc)

                                        new_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)

                                

                                # Eliminar firmas si está activado

                                if remove_signatures and new_doc.page_count > 0:

                                    for page in new_doc:

                                        for widget in page.widgets():

                                            if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:

                                                page.delete_widget(widget)

                                

                                if new_doc.page_count > 0:

                                    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

                                    new_doc.save(tmp_path)

                                    new_doc.close()

                                    for src_doc in open_src_docs:

                                        try:

                                            src_doc.close()

                                        except Exception:

                                            pass

                                    if dest_path.exists():

                                        try: dest_path.unlink()

                                        except: pass

                                    import shutil

                                    shutil.move(str(tmp_path), str(dest_path))

                                    saved_files.append(dest_path)

                        elif box.file_path and Path(box.file_path).exists():

                            # Fallback: Copy original file only if no pages available

                            # (e.g., boxes loaded directly without expanding)

                            # Safe Save

                            tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")



                            # Si está activada la opción, NO copiamos tal cual porque se colarían

                            # los campos de firma digital. Generamos un PDF nuevo sin firmas.

                            if remove_signatures:

                                try:

                                    src_doc = fitz.open(box.file_path)

                                    new_doc = fitz.open()

                                    new_doc.insert_pdf(src_doc)



                                    if new_doc.page_count > 0:

                                        for page in new_doc:

                                            for widget in page.widgets():

                                                if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:

                                                    page.delete_widget(widget)



                                    new_doc.save(tmp_path)

                                    new_doc.close()

                                    # Cerrar la fuente después de guardar/cerrar el destino.
                                    src_doc.close()

                                except Exception as e:

                                    # Fallback seguro: si falla el saneado, copiamos el archivo original.

                                    log.error(f"Error eliminando firmas al guardar {box.name}: {e}")

                                    import shutil

                                    shutil.copy2(box.file_path, tmp_path)

                            else:

                                import shutil

                                shutil.copy2(box.file_path, tmp_path)



                            if dest_path.exists():

                                try: dest_path.unlink()

                                except: pass



                            import shutil

                            shutil.move(str(tmp_path), str(dest_path))

                            saved_files.append(dest_path)

                    except Exception as e:

                        # Diagnóstico de errores en Modo Cajas

                        err_str = str(e).lower()

                        culprit = None

                        if "cycle" in err_str or "structure" in err_str or "code=7" in err_str:

                            log.info(f"Detectado error estructural en caja {box.name}, diagnosticando...")

                            self.root.after(0, lambda: self.update_status(f"Diagnosticando error en {box.name}..."))

                            

                            # Determinar estrategia de diagnóstico según el tipo de contenido de la caja

                            if hasattr(box, 'metadata') and box.metadata.get('merged_file_paths'):

                                culprit = self.viewer.diagnose_save_error_paths(box.metadata['merged_file_paths'])

                            elif hasattr(box, 'page_refs') and box.page_refs:

                                culprit = self.viewer.diagnose_save_error_refs(box.page_refs)

                            elif box.file_path:

                                culprit = self.viewer.diagnose_save_error_paths([box.file_path])

                        

                        if culprit:

                            log.error(f"Error saving box {box.name}: Culprit file is {culprit}")

                            print(f"Error saving {box.name}: Culprit file is {culprit}")

                            # No podemos mostrar messagebox directo desde el hilo, se acumula para el final o se lanza excepción

                            # Pero como aquí el bucle continúa, guardamos el error mejorado

                            error_msg = f"Error en {box.name}: El archivo original '{Path(culprit).name}' está corrupto (cycle/structure error)."

                            # Lanzar excepción o manejarlo para que se reporte al usuario al final

                            # Como este bloque catch solo logueaba, ahora lanzaremos una excepción controlada para que save_worker la capture

                            raise Exception(error_msg)

                        

                        log.error(f"Error saving box {box.name}: {e}")

                        print(f"Error saving {box.name}: {e}")

                        raise e # Re-lanzar para que se reporte en el resumen final

                        

                # 2. Combined file

                if combined_name:

                    comb_filename = combined_name

                    if not comb_filename.lower().endswith(".pdf"):

                        comb_filename += ".pdf"

                        

                    combined_path = target_path / comb_filename

                    try:

                        merged_doc = fitz.open()

                        open_src_docs = []

                        # Recolectar todos los paths involucrados para diagnóstico

                        all_involved_paths = set()

                        

                        for item in to_save:

                            box = item["section"].original_box

                            

                            # Priority: Check if this is a merged box with file paths

                            if hasattr(box, 'metadata') and box.metadata.get('merged_file_paths'):

                                # Merged box - load from all source files

                                merged_paths = box.metadata['merged_file_paths']

                                for file_path in merged_paths:

                                    all_involved_paths.add(file_path)

                                    try:

                                        src_doc = fitz.open(file_path)

                                        open_src_docs.append(src_doc)

                                        merged_doc.insert_pdf(src_doc)

                                    except Exception as e:

                                        log.error(f"Error loading merged file {file_path}: {e}")

                            # NUEVO: Verificar si tiene PageReference (método preferido)

                            elif hasattr(box, 'page_refs') and box.page_refs and len(box.page_refs) > 0:

                                from src.pdf.structure import PageReference

                                first_ref = box.page_refs[0]

                                

                                if isinstance(first_ref, PageReference):

                                    # Insertar desde PageReference

                                    for ref in box.page_refs:

                                        if isinstance(ref, PageReference) and Path(ref.file_path).exists():

                                            all_involved_paths.add(ref.file_path)

                                            try:

                                                src_doc = fitz.open(ref.file_path)

                                                open_src_docs.append(src_doc)

                                                merged_doc.insert_pdf(src_doc, from_page=ref.page_index, to_page=ref.page_index)

                                            except Exception as e:

                                                log.error(f"Error loading page from {ref.file_path}:{ref.page_index}: {e}")

                                

                                # LEGACY: Tuplas (doc_index, page_index)

                                elif isinstance(first_ref, tuple) and len(first_ref) == 2:

                                    for page in box.page_refs:

                                        if isinstance(page, tuple) and len(page) == 2:

                                            doc_idx, page_idx = page

                                            doc = self.viewer.documents[doc_idx]

                                            all_involved_paths.add(str(doc.filepath))

                                            src_doc = fitz.open(doc.filepath)

                                            open_src_docs.append(src_doc)

                                            merged_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)

                            elif box.file_path and Path(box.file_path).exists():

                                # Fallback: Insert from original file

                                all_involved_paths.add(box.file_path)

                                src_doc = fitz.open(box.file_path)

                                open_src_docs.append(src_doc)

                                merged_doc.insert_pdf(src_doc)

                        

                        # Eliminar firmas del documento combinado si está activado

                        if remove_signatures and merged_doc.page_count > 0:

                            for page in merged_doc:

                                for widget in page.widgets():

                                    if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:

                                        page.delete_widget(widget)

                                

                        merged_doc.save(combined_path)

                        merged_doc.close()

                        for src_doc in open_src_docs:

                            try:

                                src_doc.close()

                            except Exception:

                                pass

                    except Exception as e:

                        # Diagnóstico para archivo combinado

                        err_str = str(e).lower()

                        culprit = None

                        if "cycle" in err_str or "structure" in err_str or "code=7" in err_str:

                            log.info(f"Detectado error estructural en combinado (Modo Cajas), diagnosticando...")

                            self.root.after(0, lambda: self.update_status(f"Diagnosticando error en combinado..."))

                            culprit = self.viewer.diagnose_save_error_paths(list(all_involved_paths))

                        

                        if culprit:

                            error_msg = f"Error en combinado: El archivo original '{Path(culprit).name}' está corrupto (cycle/structure error)."

                            log.error(f"Save error diagnosed: {error_msg}")

                            raise Exception(error_msg)

                            

                        log.error(f"Error creating combined file: {e}")

                        print(f"Error creating combined file: {e}")

                        raise e

                

                count = len(saved_files)

                self.root.after(0, lambda c=count: self.update_status(f"Guardados {c} archivos"))

                self.root.after(0, lambda c=count: messagebox.showinfo("Guardado", f"Se han guardado correctamente {c} archivos"))

                

            except Exception as e:

                error_msg = str(e)

                self.root.after(0, lambda msg=error_msg: messagebox.showerror("Error", f"Error al guardar: {msg}"))

                

        threading.Thread(target=save_worker, daemon=True).start()



    def _on_drag_start(self, index: int, event):

        """Handle drag start"""

        log.debug(f"Drag started on item {index}")

        if self.grid.box_mode:

            count = len(self.grid.selected_indices) or 1

            self.update_status(f"Arrastrando {count} caja(s)...")

        else:

            self.update_status(f"Arrastrando página {index}...")



    def _on_drag_motion(self, index: int, event):

        """Handle drag motion"""

        # Show drop target in status

        if hasattr(self.grid, 'drag_start_index'):

            if self.grid.box_mode:

                count = len(self.grid.selected_indices) or 1

                self.update_status(f"Mover {count} caja(s) → {index if index != -1 else 'fin'}")

            else:

                self.update_status(f"Mover página {self.grid.drag_start_index} → {index}")



    def _on_drag_end(self, index: int, event):

        """Handle drag end"""

        if not hasattr(self.grid, 'drag_start_index'):

            return

            

        start_idx = self.grid.drag_start_index

        target_idx = index

        

        log.debug(f"Drag ended: {start_idx} -> {target_idx}")

        

        # In box mode, reorder boxes instead of pages

        if self.grid.box_mode:

            self.add_undo_snapshot()

            if target_idx == -1:

                target_idx = len(self.grid.document_boxes)

            moved = False

            if self.grid.selected_indices:

                moved = self.grid.reorder_selected_boxes(target_idx)

            elif start_idx != target_idx and target_idx != -1:

                self.grid.reorder_boxes(start_idx, target_idx)

                moved = True



            if moved:

                # Invalidate backend sync so sections are rebuilt in new order

                # when editor is opened next time

                self.viewer.close_all()

                self.section_manager.sections = []

                

                moved_count = len(self.grid.selected_indices) or 1

                self.update_status(f"Cajas reordenadas (x{moved_count})")

            else:

                self.update_status("Listo")

            return

    

        # Get all selected pages

        selected = sorted(list(self.grid.selected_indices))

        

        if not selected:

            return



        # Check for no-op move (same position and no specific target section)

        is_same_position = (target_idx == start_idx)

        has_target_section = (hasattr(self.grid, 'drop_target_section') and self.grid.drop_target_section)

        

        if is_same_position and not has_target_section:

             self.update_status("Listo")

             return



        self.add_undo_snapshot()



        # 1. Capture State BEFORE Move (for Section Adoption)

        old_sections_map = {}  # page_index -> section_obj

        for p in selected:

            old_sections_map[p] = self.section_manager.get_section_at(p)

                    

        # Identify Target Section

        # We need to know which section receives the pages.

        dest_s = self.section_manager.get_section_at(target_idx)

        

        # Check if grid has a specific target section (dragged to end of section row)

        if has_target_section:

            dest_s = self.grid.drop_target_section

            

        # Special case: target_idx == total_pages (Appended to end).

        total_pages = self.viewer.get_page_count()

        if not dest_s and target_idx >= total_pages:

             if self.section_manager.sections:

                 dest_s = self.section_manager.sections[-1]

        

        # Special case: If target_idx is 0, belongs to first section.

        if not dest_s and target_idx == 0:

             if self.section_manager.sections:

                 dest_s = self.section_manager.sections[0]

        

        # 2. Move pages using viewer

        if is_same_position:

            success = True

        else:

            success = self.viewer.move_pages(selected, target_idx)

        

        if success:

            # 3. Update Section Counts (Adoption Logic)

            # Pages leave their old section and join the new one.

            

            # Count pages moved from each section (use section ID as key)

            source_sections_count = {}  # section_id -> (section, count)

            log.info(f"Selected pages to move: {selected}")

            for p in selected:

                s = old_sections_map.get(p)

                if s:

                    log.info(f"  Page {p} comes from section '{s.title}'")

                    if s.id not in source_sections_count:

                        source_sections_count[s.id] = [s, 0]

                    source_sections_count[s.id][1] += 1

                else:

                    log.warning(f"  Page {p} has no source section!")

            

            # Decrement sources

            for section_id, (s, count) in source_sections_count.items():

                s.page_count -= count

                log.info(f"Section '{s.title}' lost {count} pages (now {s.page_count})")

                    

            # Increment target (only if different from all sources)

            if dest_s:

                dest_s.page_count += len(selected)

                log.info(f"Section '{dest_s.title}' gained {len(selected)} pages (now {dest_s.page_count})")

            elif self.section_manager.sections:

                # Fallback if no specific target found

                self.section_manager.sections[-1].page_count += len(selected)

    

            # 4. Remove empty sections and Recalculate Offsets

            log.info(f"Sections AFTER count update (before cleanup):")

            for s in self.section_manager.sections:

                log.info(f"  {s.title}: {s.page_count} pages (special={s.is_special})")

            

            final_sections = []

            current_start = 0

            for s in self.section_manager.sections:

                # Keep sections with pages, or special sections that still have pages

                if s.page_count > 0:

                    s.start_page = current_start

                    final_sections.append(s)

                    current_start += s.page_count

                else:

                    # Section disappeared (empty)

                    log.info(f"Removed empty section: {s.title} (special={s.is_special})")

            

            # Ensure we have at least one non-special section

            saveable = [s for s in final_sections if not s.is_special]

            if not saveable:

                # Create a default section if all were removed

                default_section = Section(

                    id="default",

                    title=self.config.get_default_base_name(),

                    start_page=0,

                    page_count=self.viewer.get_page_count()

                )

                # Find deleted section and adjust

                deleted_idx = -1

                for i, s in enumerate(final_sections):

                    if s.is_special:

                        deleted_idx = i

                        break

                

                if deleted_idx >= 0:

                    deleted_section = final_sections[deleted_idx]

                    default_section.page_count -= deleted_section.page_count

                    final_sections.insert(0, default_section)

                    deleted_section.start_page = default_section.page_count

                else:

                    final_sections = [default_section]

            

            self.section_manager.sections = final_sections

            

            # Update grid selection (viewer updates its selection internally usually, but let's sync)

            self.grid.selected_indices = self.viewer.selected_pages

            

            # Refresh grid

            # CRÍTICO: tras mover páginas, `viewer.pages` cambia y el grid debe recalcular aspect ratios/tamaños

            # para que cada índice use el tamaño correcto (evita miniaturas "apaisadas"/huecos).

            total_pages = self.viewer.get_page_count()

            try:

                all_sizes = self.viewer.get_all_page_sizes()

            except Exception:

                all_sizes = None



            if all_sizes and len(all_sizes) == total_pages:

                self.grid.set_item_count(total_pages, page_sizes=all_sizes)

            else:

                self.grid.set_item_count(total_pages)



            # Reaplicar marcas (X roja) y secciones tras el refresh.

            if hasattr(self.grid, 'marked_indices'):

                self.grid.marked_indices = set(self.viewer.marked_pages)

            self.grid.set_sections(self.section_manager.sections)

            

            self.update_status(f"Movidas {len(selected)} páginas a posición {target_idx}")

        else:

            self.update_status("Error al mover páginas")



    def update_status(self, text: str):

        """Update status bar text"""

        # Guardamos el texto completo; el label puede mostrar una versión

        # truncada con "..." si no cabe (ver _layout_status_and_zoom).

        self._status_full_text = text

        if not self._layout_status_and_zoom():

            # Widgets aún sin mapear: aplicamos el texto sin restricción;

            # el primer <Configure> de la barra lo truncará si hace falta.

            self._apply_status_text(text, 10**6)



    def _status_measure_font(self):

        """Devuelve una fuente tkinter medible a partir de default_font"""

        try:

            import tkinter.font as tkfont

            return tkfont.Font(font=self.default_font)

        except Exception:

            return None



    def _current_status_avail(self) -> int:

        """Ancho en px disponible para el texto de estado, según haya zoom visible o no"""

        try:

            bar_w = self.status_bar.winfo_width()

            label_x = self.status_label.winfo_x()

            right_x = self.footer_right.winfo_x()

        except Exception:

            return 10**6



        # Widgets aún sin mapear: sin restricción

        if bar_w <= 1 or right_x <= 1 or label_x <= 1:

            return 10**6



        label_right_limit = right_x - 6

        if getattr(self, "_zoom_visible", False):

            zoom_w = self.footer_zoom.winfo_reqwidth()

            zoom_x0 = (bar_w - zoom_w) / 2

            label_right_limit = min(label_right_limit, zoom_x0 - 8)

        return max(60, int(label_right_limit - label_x))



    def _on_footer_configure(self, event=None):

        """Relanza el layout del footer en el siguiente ciclo del event loop.

        OJO: se usa root.after_idle porque PodofiloApp no es un widget Tk y no

        tiene ni after() ni after_idle() propios.

        """

        try:

            self.root.after_idle(self._safe_layout_status_and_zoom)

        except Exception:

            self._safe_layout_status_and_zoom()



    def _safe_layout_status_and_zoom(self):

        """_layout_status_and_zoom con protección de excepciones (corre en el event loop)"""

        try:

            self._layout_status_and_zoom()

        except Exception:

            log.debug("Error redistribuyendo el footer", exc_info=True)



    def _layout_status_and_zoom(self) -> bool:

        """Redistribuye el footer:

        - Trunca el texto de estado con '...' si llega a la zona de zoom.

        - Oculta los botones de zoom si no hay espacio suficiente, de modo que

          el cluster derecho (EXPANDIR/CAJAS, OVE...) nunca quede tapado.

        Devuelve False si los widgets aún no están mapeados.

        """

        try:

            bar_w = self.status_bar.winfo_width()

            label_x = self.status_label.winfo_x()

            right_x = self.footer_right.winfo_x()

        except Exception:

            return False



        # Widgets aún sin mapear: no hay nada que calcular

        if bar_w <= 1 or right_x <= 1 or label_x <= 1:

            return False



        # Footer de zoom aún no creado (llamada muy temprana en el arranque):

        # no hay zona de zoom, pero igualmente refrescamos el texto visible.

        if not hasattr(self, "footer_zoom"):

            self._refresh_status_label_display()

            return True

        zoom_w = self.footer_zoom.winfo_reqwidth()



        # 1) Visibilidad de los botones de zoom (solo con editor activo).

        #    El grupo va centrado en la barra, así que debe cumplir ambas:

        #    - no pisar el cluster derecho (prioridad absoluta de EXPANDIR/

        #      CAJAS, OVE...), y

        #    - dejar un mínimo de sitio al texto de estado.

        #    Si no se cumplen, los botones de zoom desaparecen.

        zoom_left = (bar_w - zoom_w) / 2

        zoom_right = (bar_w + zoom_w) / 2

        cabe_izquierda = zoom_left >= label_x + 70

        cabe_derecha = zoom_right <= right_x - 8

        if getattr(self, "editor_active", False) and cabe_izquierda and cabe_derecha:

            if not getattr(self, "_zoom_visible", False):

                self.footer_zoom.place(relx=0.5, rely=0.5, anchor="center")

                self._zoom_visible = True

        else:

            if getattr(self, "_zoom_visible", False):

                self.footer_zoom.place_forget()

                self._zoom_visible = False



        # 2) Refrescar texto (truncado con "..." si procede)

        self._refresh_status_label_display()

        return True



    def _refresh_status_label_display(self):

        """Aplica el texto visible actual (tooltip temporal o normal) truncado al ancho disponible"""

        if getattr(self, "_status_hover_active", False):

            text = getattr(self, "_status_hover_text", "")

        else:

            text = getattr(self, "_status_full_text", "")

        self._apply_status_text(text, self._current_status_avail())



    def _apply_status_text(self, text: str, avail: int):

        """Configura el label de estado truncando 'text' a 'avail' píxeles"""

        font = self._status_measure_font()

        display = text or ""

        if font is not None and text:

            try:

                if font.measure(text) > avail:

                    ell = "..."

                    lo, hi = 0, len(text)

                    # Búsqueda binaria del prefijo más largo que quepa con "..."

                    while lo < hi:

                        mid = (lo + hi + 1) // 2

                        if font.measure(text[:mid] + ell) <= avail:

                            lo = mid

                        else:

                            hi = mid - 1

                    display = (text[:lo].rstrip() + ell) if lo > 0 else ell

            except Exception:

                display = text



        # Solo reconfiguramos si cambia el texto visible (evita bucles de Configure)

        try:

            if self.status_label.cget("text") != display:

                self.status_label.configure(text=display)

        except Exception:

            pass



    def _show_status_tooltip(self, text: str):

        """Muestra un mensaje temporal en la barra de estado sin perder el texto previo."""

        if not text:

            self._clear_status_tooltip()

            return



        if not getattr(self, "_status_hover_active", False):

            try:

                self._status_hover_prev_text = self.status_label.cget("text")

            except Exception:

                self._status_hover_prev_text = ""



        self._status_hover_active = True

        self._status_hover_text = text

        # Muestra el mensaje temporal truncado si no cabe (mismo criterio que

        # el texto normal de la barra de estado).

        self._refresh_status_label_display()



    def _clear_status_tooltip(self):

        """Restaura el estado anterior al cerrar el tooltip temporal."""

        if not getattr(self, "_status_hover_active", False):

            return



        self._status_hover_active = False

        self._status_hover_prev_text = ""

        self._status_hover_text = ""

        # Restauramos el texto de estado completo (truncado si procede).

        # Aunque update_status haya llegado durante el hover, _status_full_text

        # guarda siempre el último mensaje real.

        self._refresh_status_label_display()



    def _on_box_hover_status(self, index: Optional[int]):

        """Actualiza la barra de estado con el motivo de error al pasar por cajas FAILED."""

        if index is None or not getattr(self.grid, "box_mode", False):

            self._clear_status_tooltip()

            return



        box = self.grid.get_box_at(index)

        if not box or box.state != BoxState.FAILED:

            self._clear_status_tooltip()

            return



        error_msg = (getattr(box, "error_message", "") or "").strip()

        if error_msg:

            hover_text = f"Error en '{box.name}': {error_msg}"

        else:

            hover_text = f"Error en '{box.name}': no se pudo cargar. Click para reintentar."



        self._show_status_tooltip(hover_text)



    def update_title(self, filename: str = None):

        """Update window title with filename"""

        title = "Podofilo V2 - PDF Manager"

        if self.version_label:

            title = f"{title} ({self.version_label})"

            

        if filename:

            title = f"{title} - {filename}"

            

        self.root.title(title)



    def _snap_to_zoom_level(self, size: int) -> int:

        """Ajustar tamaño al nivel de zoom más cercano (miniaturas)"""

        closest = min(self.zoom_levels, key=lambda x: abs(x - size))

        return closest



    def _snap_to_box_zoom_level(self, size: int) -> int:

        """Ajustar tamaño al nivel de zoom de cajas más cercano"""

        closest = min(self.box_zoom_levels, key=lambda x: abs(x - size))

        return closest



    def _get_zoom_percentage(self, size: int) -> int:

        """Convertir tamaño de thumbnail a porcentaje (base: 150px = 100%)"""

        return int((size / 150) * 100)



    def _get_box_zoom_percentage(self, size: int) -> int:

        """Convertir tamaño de caja a porcentaje (base: 200px = 100%)"""

        return int((size / 200) * 100)



    def zoom_in(self, event=None):

        """Increase thumbnail/box size"""

        if self.grid.box_mode:

            # Modo CAJAS: usar niveles de cajas

            current_idx = self.box_zoom_levels.index(self.box_thumbnail_size) if self.box_thumbnail_size in self.box_zoom_levels else -1

            if current_idx == -1:

                next_level = next((lvl for lvl in self.box_zoom_levels if lvl > self.box_thumbnail_size), self.box_zoom_levels[-1])

            elif current_idx < len(self.box_zoom_levels) - 1:

                next_level = self.box_zoom_levels[current_idx + 1]

            else:

                return

            self.box_thumbnail_size = next_level

            self.grid.set_box_thumbnail_size(next_level)

            self.config.set_box_thumbnail_size(next_level)

            self.update_status(f"Zoom cajas: {self._get_box_zoom_percentage(next_level)}%")

            return



        current_idx = self.zoom_levels.index(self.thumbnail_size) if self.thumbnail_size in self.zoom_levels else -1

        

        if current_idx == -1:

            # No está en un nivel exacto, ajustar al siguiente nivel superior

            next_level = next((level for level in self.zoom_levels if level > self.thumbnail_size), self.zoom_levels[-1])

        elif current_idx < len(self.zoom_levels) - 1:

            # Ir al siguiente nivel

            next_level = self.zoom_levels[current_idx + 1]

        else:

            # Ya está en el máximo

            return

        

        self.thumbnail_size = next_level

        self.grid.set_thumbnail_size(next_level)

        self.config.set_thumbnail_size(next_level)

        self.update_status(f"Zoom: {self._get_zoom_percentage(next_level)}%")

    

    def zoom_out(self, event=None):

        """Decrease thumbnail/box size"""

        if self.grid.box_mode:

            # Modo CAJAS: usar niveles de cajas

            current_idx = self.box_zoom_levels.index(self.box_thumbnail_size) if self.box_thumbnail_size in self.box_zoom_levels else -1

            if current_idx == -1:

                prev_level = next((lvl for lvl in reversed(self.box_zoom_levels) if lvl < self.box_thumbnail_size), self.box_zoom_levels[0])

            elif current_idx > 0:

                prev_level = self.box_zoom_levels[current_idx - 1]

            else:

                return

            self.box_thumbnail_size = prev_level

            self.grid.set_box_thumbnail_size(prev_level)

            self.config.set_box_thumbnail_size(prev_level)

            self.update_status(f"Zoom cajas: {self._get_box_zoom_percentage(prev_level)}%")

            return



        # Encontrar el nivel anterior de zoom

        current_idx = self.zoom_levels.index(self.thumbnail_size) if self.thumbnail_size in self.zoom_levels else -1

        

        if current_idx == -1:

            # No está en un nivel exacto, ajustar al siguiente nivel inferior

            prev_level = next((level for level in reversed(self.zoom_levels) if level < self.thumbnail_size), self.zoom_levels[0])

        elif current_idx > 0:

            # Ir al nivel anterior

            prev_level = self.zoom_levels[current_idx - 1]

        else:

            # Ya está en el mínimo

            return

        

        self.thumbnail_size = prev_level

        self.grid.set_thumbnail_size(prev_level)

        self.config.set_thumbnail_size(prev_level)

        self.update_status(f"Zoom: {self._get_zoom_percentage(prev_level)}%")

            

    def zoom_reset(self, event=None):

        """Reset thumbnail/box size"""

        if self.grid.box_mode:

            self.box_thumbnail_size = 200

            self.grid.set_box_thumbnail_size(200)

            self.config.set_box_thumbnail_size(200)

            self.update_status("Zoom cajas: 100%")

            return



        self.thumbnail_size = 150

        self.grid.set_thumbnail_size(150)

        self.config.set_thumbnail_size(150)

        self.update_status("Zoom: 100%")

    

    def on_mouse_wheel(self, event):

        """Handle mouse wheel events for zoom with CTRL"""

        # Check if CTRL is pressed

        if event.state & 0x4:  # 0x4 is the Control key mask

            # Zoom funciona tanto en modo páginas como en modo CAJAS

            # event.delta is positive for scroll up, negative for scroll down

            # On Windows, delta is typically 120 or -120

            if event.delta > 0:

                # Scroll up = Zoom in

                self.zoom_in()

            elif event.delta < 0:

                # Scroll down = Zoom out

                self.zoom_out()

            # Return "break" to prevent the event from propagating

            return "break"

    

    def _on_return_key(self, event=None):

        """Handle Return/Enter key - expand boxes in box mode, open editor in page mode"""

        if self.grid.box_mode:

            # En modo CAJAS, expandir las cajas

            self.expand_all_boxes()

        else:

            # En modo páginas, abrir editor si hay exactamente 1 página seleccionada

            if len(self.viewer.selected_pages) == 1:

                page_index = next(iter(self.viewer.selected_pages))

                self.open_page_editor_for_page(page_index)

    

    def _on_arrow_left(self, event=None):

        """Move selection to the left (Ctrl to add to selection)"""

        if self.grid.box_mode:

            return  # No navegar en modo CAJAS

        

        total_pages = self.viewer.get_page_count()

        if total_pages == 0:

            return

        

        # Detectar si Ctrl está pulsado

        ctrl_pressed = event and (event.state & 0x4)

        

        if not self.viewer.selected_pages:

            new_index = total_pages - 1

        else:

            min_selected = min(self.viewer.selected_pages)

            new_index = max(0, min_selected - 1)

        

        # Actualizar selección

        if ctrl_pressed:

            self.viewer.selected_pages.add(new_index)

        else:

            self.viewer.selected_pages = {new_index}

        self.grid.selected_indices = self.viewer.selected_pages.copy()

        self.grid.redraw()

        self._on_selection_change()

        self.grid.scroll_to_item(new_index)

    

    def _on_arrow_right(self, event=None):

        """Move selection to the right (Ctrl to add to selection)"""

        if self.grid.box_mode:

            return  # No navegar en modo CAJAS

        

        total_pages = self.viewer.get_page_count()

        if total_pages == 0:

            return

        

        # Detectar si Ctrl está pulsado

        ctrl_pressed = event and (event.state & 0x4)

        

        if not self.viewer.selected_pages:

            new_index = 0

        else:

            max_selected = max(self.viewer.selected_pages)

            new_index = min(total_pages - 1, max_selected + 1)

        

        # Actualizar selección

        if ctrl_pressed:

            self.viewer.selected_pages.add(new_index)

        else:

            self.viewer.selected_pages = {new_index}

        self.grid.selected_indices = self.viewer.selected_pages.copy()

        self.grid.redraw()

        self._on_selection_change()

        self.grid.scroll_to_item(new_index)

    

    def _on_arrow_up(self, event=None):

        """Move selection up (Ctrl to add to selection)"""

        if self.grid.box_mode:

            return

        

        total_pages = self.viewer.get_page_count()

        if total_pages == 0:

            return

        

        # Detectar si Ctrl está pulsado

        ctrl_pressed = event and (event.state & 0x4)

        

        if not self.viewer.selected_pages:

            new_index = total_pages - 1

        else:

            current = min(self.viewer.selected_pages)

            new_index = self.grid.find_item_above(current)

            if new_index is None:

                new_index = current

        

        # Actualizar selección

        if ctrl_pressed:

            self.viewer.selected_pages.add(new_index)

        else:

            self.viewer.selected_pages = {new_index}

        self.grid.selected_indices = self.viewer.selected_pages.copy()

        self.grid.redraw()

        self._on_selection_change()

        self.grid.scroll_to_item(new_index)

    

    def _on_arrow_down(self, event=None):

        """Move selection down (Ctrl to add to selection)"""

        if self.grid.box_mode:

            return

        

        total_pages = self.viewer.get_page_count()

        if total_pages == 0:

            return

        

        # Detectar si Ctrl está pulsado

        ctrl_pressed = event and (event.state & 0x4)

        

        if not self.viewer.selected_pages:

            new_index = 0

        else:

            current = max(self.viewer.selected_pages)

            new_index = self.grid.find_item_below(current)

            if new_index is None:

                new_index = current

        

        # Actualizar selección

        if ctrl_pressed:

            self.viewer.selected_pages.add(new_index)

        else:

            self.viewer.selected_pages = {new_index}

        self.grid.selected_indices = self.viewer.selected_pages.copy()

        self.grid.redraw()

        self._on_selection_change()

        self.grid.scroll_to_item(new_index)

    

    def toggle_selection(self, event=None):

        """Toggle between select all and deselect all (Espacio)"""

        if self._grid_action_blocked():

            return

        if self.grid.box_mode:

            total_boxes = len(self.grid.document_boxes)

            if total_boxes == 0:

                return



            # Si no están todas seleccionadas, seleccionar todas; de lo contrario, limpiar

            if len(self.grid.selected_indices) < total_boxes:

                self.grid.selected_indices = set(range(total_boxes))

            else:

                self.grid.selected_indices.clear()



            self.grid.bracket_start = None

            self.grid.redraw()

            self._on_selection_change()

            return



        self.viewer.toggle_selection()

        self.grid.selected_indices = self.viewer.selected_pages.copy()

        self.grid.redraw()

        self._on_selection_change()

    

    def rotate_selected(self, event=None):

        """Rotate selected pages 90° clockwise (Ctrl+R)"""

        if self._grid_action_blocked():

            return

        if not self.viewer.selected_pages:

            return

            

        self.add_undo_snapshot()

        

        selected_indices = list(self.viewer.selected_pages)

        self.viewer.rotate_selected_pages(90)

        

        # Clear cached images for rotated pages to force re-render

        for idx in selected_indices:

            if idx in self.grid.images:

                del self.grid.images[idx]

        

        # Recalculate item sizes for rotated pages (dimensions change)

        self._update_grid_item_sizes()

        

        self.grid.redraw()

        self.update_status(f"Rotadas {len(selected_indices)} páginas 90° horario")

    

    def insert_blank_pages(self, event=None):

        """Insert blank pages after selection or at end (Shift+D)"""

        if self._grid_action_blocked():

            return

        self.add_undo_snapshot()

        count_before = len(self.viewer.selected_pages) if self.viewer.selected_pages else 1

        self.viewer.insert_blank_pages()

        

        # Update sections - extend last section to include new pages

        if self.section_manager.sections:

            last_section = self.section_manager.sections[-1]

            last_section.page_count += count_before

        

        # Update grid

        self.grid.set_item_count(self.viewer.get_page_count())

        self.grid.set_sections(self.section_manager.sections)

        self.grid.selected_indices = self.viewer.selected_pages.copy()

        self.grid.redraw()

        

        if count_before == 1:

            self.update_status("Insertada 1 página en blanco")

        else:

            self.update_status(f"Insertadas {count_before} páginas en blanco")

    

    def duplicate_selected(self, event=None):

        """Duplicate selected pages (D)"""

        if self._grid_action_blocked():

            return

        if not self.viewer.selected_pages:

            return

        

        self.add_undo_snapshot()

        count_before = len(self.viewer.selected_pages)

        self.viewer.duplicate_selected_pages()

        

        # Update sections - extend last section to include new pages

        if self.section_manager.sections:

            last_section = self.section_manager.sections[-1]

            last_section.page_count += count_before

        

        # Update grid

        self.grid.set_item_count(self.viewer.get_page_count())

        self.grid.set_sections(self.section_manager.sections)

        self.grid.selected_indices = self.viewer.selected_pages.copy()

        self.grid.redraw()

        

        self.update_status(f"Duplicadas {count_before} páginas")

    

    def start_keyboard_move(self, event=None):

        """

        Inicia el modo de movimiento con teclado (tecla M).

        Activa el efecto abanico y espera un click para completar el movimiento.

        Funciona tanto en modo páginas como en modo cajas.

        """

        if self._grid_action_blocked():

            return

        if self.grid.start_keyboard_move():

            # Determinar mensaje según el modo

            if self.grid.box_mode:

                count = len(self.grid.selected_indices)

                self.update_status(f"Modo mover: haz click en la posición destino para mover {count} caja(s) (ESC para cancelar)")

            else:

                count = len(self.grid.selected_indices)

                self.update_status(f"Modo mover: haz click en la posición destino para mover {count} página(s) (ESC para cancelar)")

        else:

            # No se pudo activar (sin selección, en modo corte, etc.)

            if not self.grid.selected_indices:

                self.update_status("Selecciona páginas/cajas para mover")

            elif self.grid.cut_mode:

                self.update_status("Desactiva el modo corte (ESC) antes de mover")

        

        return "break"

    

    def delete_selected(self, event=None):

        """Delete selected pages/boxes (Supr)"""

        # Bloqueado en modo Edición: borrar páginas "a ciegas" tras el editor

        # puede dejar el editor apuntando a una página inexistente.

        if self._grid_action_blocked():

            return

        # --- 1. BOX MODE DELETION ---

        if self.grid.box_mode:

            self.delete_selected_boxes()

            return

            

        # --- 2. PAGE MODE DELETION ---

        if not self.viewer.selected_pages:

            return

        

        self.add_undo_snapshot()

        selected = sorted(list(self.viewer.selected_pages))

        count = len(selected)

        

        # Check if we are deleting from "Borrados" (Permanent Delete)

        # Use first selected page to determine section. (Assuming mixed selection behaves as standard delete)

        first_page_idx = selected[0]

        section = self.section_manager.get_section_at(first_page_idx)

        

        if section and section.is_special and section.id == "deleted":

            # PERMANENT DELETION

            if messagebox.askyesno("Eliminar definitivamente", 

                                 f"¿Estás seguro de eliminar definitivamente {count} páginas?\nEsta acción no se puede deshacer."):

                 # Use explicit delete_pages instead of default delete_selected_pages (which moves)

                 self.viewer.delete_pages(selected)

                 

                 # Special section handling: manually update count

                 section.page_count -= count

                 self._refresh_sections_after_delete()

                 self.update_status(f"Eliminadas definitivamente {count} páginas")

            else:

                 # Restore undo stack if cancelled (optional, but clean)

                 pass

            return

            

        # NORMAL DELETION (Move to Borrados)

        # Map pages to their sections BEFORE deletion

        pages_per_section = {}  # section_id -> count

        for page_idx in selected:

            section = self.section_manager.get_section_at(page_idx)

            if section and not section.is_special:

                if section.id not in pages_per_section:

                    pages_per_section[section.id] = 0

                pages_per_section[section.id] += 1

        

        # Check if deleted section already exists

        deleted_section_exists = any(s.is_special for s in self.section_manager.sections)

        previous_deleted = 0

        if deleted_section_exists:

            for s in self.section_manager.sections:

                if s.is_special:

                    previous_deleted = s.page_count

                    break

        

        # Delete pages (This moves them out of current structure in FitZ helper usually, 

        # or we just logically move them. Viewer.delete_selected_pages deletes them from document list)

        self.viewer.delete_selected_pages()

        

        # Get or create 'Borrados' section

        deleted_section = self.section_manager.get_deleted_section()

        

        # Update deleted section counts (accumulate)

        deleted_section.page_count = previous_deleted + count

        

        # Decrement page counts from source sections

        for section in self.section_manager.sections:

            if not section.is_special and section.id in pages_per_section:

                section.page_count -= pages_per_section[section.id]

                log.info(f"Section '{section.title}' lost {pages_per_section[section.id]} pages (now {section.page_count})")

        

        self._refresh_sections_after_delete()

        self.update_status(f"Movidas {count} páginas a Borrados")



    def _refresh_sections_after_delete(self):

        """Recalculate starts and redraw grid after deletion"""

        # Recalculate section start_page offsets

        current_start = 0

        for section in self.section_manager.sections:

            section.start_page = current_start

            current_start += section.page_count

            

        # Update deleted section start if it exists

        if self.section_manager.sections and self.section_manager.sections[-1].is_special:

             self.section_manager.sections[-1].start_page = self.viewer.get_page_count() - self.section_manager.sections[-1].page_count



        # Update grid

        self.grid.set_item_count(self.viewer.get_page_count())

        self.grid.set_sections(self.section_manager.sections)

        self.grid.selected_indices.clear()

        self.grid.redraw()



    def delete_selected_boxes(self):

        """Delete selected boxes"""

        if not self.grid.selected_indices:

            return

            

        if not messagebox.askyesno("Eliminar cajas", "¿Eliminar las cajas seleccionadas de la lista?"):

            return

            

        # self.add_undo_snapshot() # TODO: Box mode undo support

        

        indices = sorted(list(self.grid.selected_indices), reverse=True)

        for i in indices:

            if 0 <= i < len(self.grid.document_boxes):

                box = self.grid.document_boxes.pop(i)

                # Cancel loading if needed

                if hasattr(box, 'cancel'):

                    box.cancel()

        

        pass # Refresh

        self.grid.selected_indices.clear()

        self.grid.set_box_mode(self.grid.document_boxes)

        self.update_status(f"Eliminadas {len(indices)} cajas")



    

    def mark_selected_blank(self, event=None):

        """Mark selected pages as blank (B)"""

        if self._grid_action_blocked():

            return

        if not self.viewer.selected_pages:

            return

        

        self.add_undo_snapshot()

        selected_count = len(self.viewer.selected_pages)

        marked_before = len(self.viewer.marked_pages)

        

        self.viewer.mark_selected_as_blank()

        

        marked_after = len(self.viewer.marked_pages)

        newly_marked = marked_after - marked_before

        

        self.grid.marked_indices = self.viewer.marked_pages.copy()

        self.grid.redraw()

        

        if newly_marked > 0:

            self.update_status(f"Detectadas y marcadas {newly_marked} páginas en blanco de {selected_count} seleccionadas")

        else:

            self.update_status(f"No se detectaron páginas en blanco en las {selected_count} páginas seleccionadas")

    

    def unmark_selected(self, event=None):

        """Unmark selected pages (Shift+B)"""

        if self._grid_action_blocked():

            return

        if not self.viewer.selected_pages:

            return

        

        self.add_undo_snapshot()

        unmarked_count = len(self.viewer.selected_pages & self.viewer.marked_pages)

        self.viewer.unmark_selected()

        self.grid.marked_indices = self.viewer.marked_pages.copy()

        self.grid.redraw()

        

        self.update_status(f"Desmarcadas {unmarked_count} páginas")

    

    def delete_marked(self, event=None):

        """Delete all marked pages (X) - moves to 'Borrados' section"""

        if self._grid_action_blocked():

            return

        if not self.viewer.marked_pages:

            self.update_status("No hay páginas marcadas para borrar")

            return

        

        self.add_undo_snapshot()

        marked = sorted(list(self.viewer.marked_pages))

        count = len(marked)

        

        # Map pages to their sections BEFORE deletion

        pages_per_section = {}  # section_id -> count

        for page_idx in marked:

            section = self.section_manager.get_section_at(page_idx)

            if section and not section.is_special:

                if section.id not in pages_per_section:

                    pages_per_section[section.id] = 0

                pages_per_section[section.id] += 1

        

        # Get current deleted count before adding more

        deleted_section = self.section_manager.get_deleted_section() if any(s.is_special for s in self.section_manager.sections) else None

        previous_deleted = deleted_section.page_count if deleted_section else 0

        

        # Delete marked pages

        self.viewer.delete_marked_pages()

        

        # Update 'Borrados' section

        deleted_section = self.section_manager.get_deleted_section()

        deleted_section.page_count = previous_deleted + count

        deleted_section.start_page = self.viewer.get_page_count() - deleted_section.page_count

        

        # Decrement page counts from source sections

        for section in self.section_manager.sections:

            if not section.is_special and section.id in pages_per_section:

                section.page_count -= pages_per_section[section.id]

                log.info(f"Section '{section.title}' lost {pages_per_section[section.id]} marked pages (now {section.page_count})")

        

        # Recalculate section start_page offsets

        current_start = 0

        for section in self.section_manager.sections:

            section.start_page = current_start

            current_start += section.page_count

        

        # Update grid

        self.grid.set_item_count(self.viewer.get_page_count())

        self.grid.set_sections(self.section_manager.sections)

        self.grid.selected_indices.clear()

        self.grid.marked_indices.clear()

        self.grid.redraw()

        

        self.update_status(f"Movidas {count} páginas marcadas a Borrados")



    def _update_grid_item_sizes(self):

        """Recalculate grid item sizes (needed after rotation)"""

        self.grid.item_sizes = []

        for i in range(self.viewer.get_page_count()):

            img = self._on_request_image(i, self.thumbnail_size)

            if img:

                self.grid.item_sizes.append((img.width, img.height))

            else:

                self.grid.item_sizes.append((self.thumbnail_size, self.thumbnail_size))

        self.grid._update_layout()

    

    def _ensure_backend_sync(self):

        """

        Ensures self.viewer and self.section_manager are populated from Boxes 

        if we are in Box Mode. This is required for Editor access, Split, etc.

        """

        # If not in box mode, we assume viewer is already the source of truth

        if not self.grid.box_mode:

            return True



        # Need at least one box to sync

        if not self.grid.document_boxes:

            return False

        

        # Verificar si las secciones coinciden con las cajas actuales.

        # Después de fusionar/dividir cajas, las secciones pueden estar desactualizadas.

        sections_match_boxes = (

            len(self.section_manager.sections) == len(self.grid.document_boxes) and

            all(sec.title == box.name 

                for sec, box in zip(self.section_manager.sections, self.grid.document_boxes))

        )

        

        # Si ya hay páginas Y las secciones coinciden, asumir sincronizado

        if self.viewer.get_page_count() > 0 and sections_match_boxes:

            return True

        

        # Si hay páginas pero las secciones no coinciden, necesitamos re-sincronizar

        if self.viewer.get_page_count() > 0 and not sections_match_boxes:

            log.info("Sections don't match boxes, re-syncing backend...")



        log.info("Syncing backend from Boxes (Lazy Initialization)...")

        from src.pdf.structure import Section

        

        # Clear current viewer state to ensure clean slate

        # We must load documents properly into PdfViewer so it can render pages

        self.viewer.close_all()

        self.section_manager.sections = []

        

        # CRÍTICO: Si hay cajas con section_id (colapsadas/divididas), sus páginas son tuplas

        # (doc_idx, page_num) que referencian viewer.documents. Necesitamos restaurar

        # viewer.documents ANTES de usar esas tuplas.

        has_collapsed_boxes = any(

            box.metadata.get('section_id') and box.pages and 

            any(isinstance(p, tuple) and len(p) == 2 for p in box.pages)

            for box in self.grid.document_boxes

            if hasattr(box, 'metadata') and hasattr(box, 'pages')

        )

        

        if has_collapsed_boxes:

            # Restaurar viewer.documents desde backup si está disponible

            if hasattr(self, '_viewer_doc_paths_backup') and self._viewer_doc_paths_backup:

                log.info(f"Restoring {len(self._viewer_doc_paths_backup)} documents for collapsed boxes")

                for doc_path in self._viewer_doc_paths_backup:

                    if doc_path:

                        try:

                            self.viewer.documents.append(PdfDocument(str(doc_path)))

                        except Exception as e:

                            log.warning(f"Failed to restore document {doc_path}: {e}")

            else:

                # Intentar derivar paths desde file_path de las cajas

                log.info("No backup available, trying to derive document paths from boxes")

                seen_paths = set()

                for box in self.grid.document_boxes:

                    path = getattr(box, 'file_path', None)

                    if path and str(path) not in seen_paths:

                        try:

                            self.viewer.documents.append(PdfDocument(str(path)))

                            seen_paths.add(str(path))

                        except Exception as e:

                            log.warning(f"Failed to load document {path}: {e}")

        

        current_page_idx = 0

        

        for box in self.grid.document_boxes:

            try:

                added_count = 0

                

                # NUEVO: Verificar si tiene PageReference (método preferido)

                if box.page_refs and len(box.page_refs) > 0:

                    first_ref = box.page_refs[0]

                    

                    if isinstance(first_ref, PageReference):

                        # Cargar desde PageReference (simple y consistente)

                        log.info(f"Syncing box '{box.name}' from {len(box.page_refs)} PageReferences")

                        added_count = self.viewer.load_from_page_refs(box.page_refs)

                    

                    elif isinstance(first_ref, tuple) and len(first_ref) == 2:

                        # LEGACY: Tuplas (doc_idx, page_num)

                        safe_pages = [p for p in box.page_refs if isinstance(p, tuple) and len(p) == 2]

                        if safe_pages:

                            added_count = len(safe_pages)

                            self.viewer.pages.extend(safe_pages)

                            log.info(f"Syncing collapsed box '{box.name}' with {added_count} tuple pages")

                        else:

                            log.warning(f"Box '{box.name}' has no valid tuple pages")

                            continue

                    

                    else:

                        # Formato desconocido - intentar file_path

                        path = getattr(box, 'file_path', None)

                        if path and Path(path).exists():

                            added_count = self.viewer.load_pdf(str(path))

                            log.info(f"Syncing box '{box.name}' from file (unknown page format)")

                        else:

                            log.warning(f"Skipping sync for box {box.name}: Unknown page format and no file_path")

                            continue

                

                else:

                    # Sin páginas - cargar desde file_path

                    path = getattr(box, 'file_path', None)

                    if not path or not Path(path).exists():

                        log.warning(f"Skipping sync for box {box.name}: No pages and no file path")

                        continue

                    

                    added_count = self.viewer.load_pdf(str(path))

                    log.info(f"Syncing box '{box.name}' from file: {added_count} pages")

                

                # Create corresponding section

                section = Section(

                    id=box.metadata.get('section_id') or f"box_{len(self.section_manager.sections)}",

                    title=box.name,

                    start_page=current_page_idx,

                    page_count=added_count

                )

                # Restore split config if available

                section.split_config = box.metadata.get('split_config')

                

                self.section_manager.sections.append(section)

                current_page_idx += added_count

                

            except Exception as e:

                log.error(f"Failed to load PDF for box {box.name}: {e}")

            

        log.info(f"Backend synced: {len(self.viewer.pages)} pages in {len(self.section_manager.sections)} sections")

        

        # CRÍTICO: Guardar backup de paths para futuras re-sincronizaciones.

        # Esto es necesario porque después de fusionar/dividir cajas, las tuplas

        # (doc_idx, page_num) siguen referenciando los mismos documentos.

        if self.viewer.documents:

            self._viewer_doc_paths_backup = [getattr(doc, 'filepath', None) for doc in self.viewer.documents]

            log.info(f"Saved document paths backup: {len(self._viewer_doc_paths_backup)} paths")

        

        return len(self.viewer.pages) > 0



    def open_page_editor(self, event=None):

        """Open page editor for selected pages (E key)"""

        

        # Box Mode Handling

        if self.grid.box_mode:

            if not self.grid.selected_indices:

                self.update_status("Selecciona una caja para editar")

                return

            

            # Take first selected box

            first_index = min(self.grid.selected_indices)

            # Use Double Click Logic (reuse code)

            self._on_thumbnail_double_click(first_index)

            return



        if not self.viewer.selected_pages:

            self.update_status("No hay páginas seleccionadas")

            return

        

        # Get first selected page

        first_page = min(self.viewer.selected_pages)

        self.open_page_editor_for_page(first_page)



    def _on_thumbnail_double_click(self, index: int):

        """Handle double click on thumbnail"""

        # If in Box Mode, index refers to the BOX index

        if self.grid.box_mode:

            box = self.grid.get_box_at(index)

            if not box:

                return

            

            # Ensure backend has data (pages/sections) so Editor can work

            if not self._ensure_backend_sync():

                self.update_status("No se puede abrir el editor: Caja no cargada o vacía")

                return



            # Find the section that corresponds to this box by name

            # After merging boxes, the index doesn't match the section index anymore

            section = None

            for sec in self.section_manager.sections:

                if sec.title == box.name:

                    section = sec

                    break

            

            if section:

                self.open_page_editor_for_page(section.start_page)

            else:

                # Fallback: use first page if we can't find the section

                log.warning(f"Could not find section for box '{box.name}', using first page")

                self.open_page_editor_for_page(0)

            return



        self.open_page_editor_for_page(index)

    

    def open_page_editor_for_page(self, page_index: int):

        """Open page editor for specific page"""

        if page_index < 0 or page_index >= self.viewer.get_page_count():

            log.warning(f"Invalid page index: {page_index}")

            return

        

        # Don't open if already in editor mode

        if self.editor_active:

            log.debug("Editor already active")

            return

        

        # Create callback to get high-res page image (match signature expected by editor)

        def get_page_image(requested_index: int, dpi: int = 150) -> Image.Image:

            return self.viewer.get_page_thumbnail(requested_index, dpi=dpi)

        

        # Hide grid

        self.grid.pack_forget()

        

        # Calculate section name first

        total_pages = self.viewer.get_page_count()

        section = self.section_manager.get_section_at(page_index)

        section_name = ""

        if section:

            # Add relative page numbering: "Title (X de Y)"

            rel_page = page_index - section.start_page + 1

            section_name = f"{section.title} ({rel_page} de {section.page_count})"



        # Create and show editor in the same frame

        self.current_editor = PageEditorWindow(

            self.content_frame,

            page_index,

            get_page_image,

            section_name=section_name,

            on_close=lambda: self._on_editor_closed(page_index)

        )

        

        # Set numbering callbacks

        self.current_editor.on_add_numbering = self.add_page_numbering

        self.current_editor.on_remove_numbering = self.remove_page_numbering

        self.current_editor.on_number_current_page = self.number_current_page

        self.current_editor.on_customize_format = self.customize_numbering_format

        self.current_editor.on_change_position = self.change_numbering_position

        self.current_editor.on_close_from_menu = self._close_editor  # For menu close

        self.current_editor.on_split_section = self._split_section_from_editor  # For splitting sections

        

        self.editor_active = True

        

        # Mostrar controles de zoom del editor (si hay espacio suficiente)

        if hasattr(self, "footer_zoom"):

            self._zoom_visible = False

            self._update_editor_fit_button()

            self._layout_status_and_zoom()

        

        # Bind ESC to close editor

        self.root.bind("<Escape>", self._close_editor)

        

        # Bind zoom controls to editor

        self.root.bind("<Control-plus>", self.current_editor.zoom_in)

        self.root.bind("<Control-equal>", self.current_editor.zoom_in)

        self.root.bind("<Control-minus>", self.current_editor.zoom_out)

        self.root.bind("<Control-0>", self.current_editor.zoom_reset)

        self.root.bind("<Control-MouseWheel>", self.current_editor.on_mouse_wheel)

        

        # Bind arrow keys to navigate pages

        self.root.bind("<Left>", self._editor_prev_page)

        self.root.bind("<Right>", self._editor_next_page)

        

        # Bind T key for adding page numbering (V1 compatibility)

        self.root.bind("t", lambda e: self.add_page_numbering())

        self.root.bind("<T>", lambda e: self.add_page_numbering())

        # Bind Shift+T for removing page numbering

        self.root.bind("<Shift-T>", lambda e: self.remove_page_numbering())

        self.root.bind("<Shift-t>", lambda e: self.remove_page_numbering())

        

        # Bind K key for splitting section at current page

        self.root.bind("k", lambda e: self._split_section_from_editor(self.current_editor.page_index) if self.current_editor else None)

        self.root.bind("<K>", lambda e: self._split_section_from_editor(self.current_editor.page_index) if self.current_editor else None)

        

        # Mostrar info de página y sección en el status

        total_pages = self.viewer.get_page_count()

        section = self.section_manager.get_section_at(page_index)

        section_name = section.title if section else ""

        if section_name:

            self.update_status(f"Página {page_index + 1} de {total_pages} ({section_name})")

        else:

            self.update_status(f"Página {page_index + 1} de {total_pages}")

    

    def _editor_prev_page(self, event=None):

        """Navigate to previous page while editor is active"""

        self._navigate_editor_page(-1)

        return "break"



    def _editor_next_page(self, event=None):

        """Navigate to next page while editor is active"""

        self._navigate_editor_page(1)

        return "break"



    def _navigate_editor_page(self, delta: int):

        """Change the page shown in the editor by delta"""

        if not self.editor_active or not self.current_editor:

            return



        total_pages = self.viewer.get_page_count()

        if total_pages == 0:

            return



        current_index = self.current_editor.page_index

        new_index = current_index + delta



        if new_index < 0:

            self.update_status("Ya estás en la primera página")

            return

        if new_index >= total_pages:

            self.update_status("Ya estás en la última página")

            return



        # Obtener nombre de la sección para mostrar en el status

        section = self.section_manager.get_section_at(new_index)

        section_name = ""

        if section:

            # Add relative page numbering: "Title (X de Y)"

            rel_page = new_index - section.start_page + 1

            section_name = f"{section.title} ({rel_page} de {section.page_count})"

        

        self.current_editor.show_page(new_index, section_name=section_name)

        self.viewer.selected_pages = {new_index}

        self.grid.selected_indices = self.viewer.selected_pages.copy()

        if section_name:

            self.update_status(f"Página {new_index + 1} de {total_pages} ({section_name})")

        else:

            self.update_status(f"Página {new_index + 1} de {total_pages}")



    def _close_editor(self, event=None):

        """Close the editor and return to grid view"""

        if self.current_editor:

            self.current_editor.close()

            self.current_editor = None

        

        self.editor_active = False

        

        # Ocultar controles de zoom del editor (solo tienen sentido en esa vista)

        if hasattr(self, "footer_zoom"):

            self.footer_zoom.place_forget()

            self._zoom_visible = False

            # El texto de estado recupera el ancho completo (sin zona de zoom)

            self._layout_status_and_zoom()

        

        # Restore grid

        self.grid.pack(fill="both", expand=True)

        

        # Restore original bindings

        self.root.bind("<Escape>", self.deactivate_cut_mode)

        self.root.bind("<Control-plus>", self.zoom_in)

        self.root.bind("<Control-equal>", self.zoom_in)

        self.root.bind("<Control-minus>", self.zoom_out)

        self.root.bind("<Control-0>", self.zoom_reset)

        self.root.bind("<Control-MouseWheel>", self.on_mouse_wheel)

        self.root.bind("<Left>", self._on_arrow_left)

        self.root.bind("<Right>", self._on_arrow_right)

        self.root.bind("<Up>", self._on_arrow_up)

        self.root.bind("<Down>", self._on_arrow_down)

        self.root.bind("t", self.add_page_numbering)

        self.root.bind("<T>", self.add_page_numbering)

        self.root.bind("<Shift-T>", self.remove_page_numbering)

        self.root.bind("<Shift-t>", self.remove_page_numbering)

        self.root.bind("k", self.toggle_cut_mode)

        self.root.bind("<K>", self.toggle_cut_mode)

    

    def _close_editor_if_active(self) -> bool:

        """Cierra el editor de páginas si está activo.

        Se usa en acciones globales que invalidan la vista del editor

        (limpiar todo, expandir/colapsar cajas, abrir PDF, índice...).

        Devuelve True si había un editor abierto y se ha cerrado.

        """

        if getattr(self, "editor_active", False):

            self._close_editor()

            return True

        return False



    def _grid_action_blocked(self) -> bool:

        """True si una acción de la vista de miniaturas debe bloquearse

        porque estamos en modo Edición (no operar 'a ciegas' tras el editor)."""

        if getattr(self, "editor_active", False):

            self.update_status("Cierra el editor (ESC) para modificar páginas en la vista de miniaturas")

            return True

        return False



    def _on_editor_closed(self, page_index: int):

        """Callback when editor closes"""

        log.debug(f"Editor closed for page {page_index}")

        # Future: Here we could refresh the thumbnail if the page was modified



    # ------------------------------------------------------------------

    # Controles de zoom del editor (footer centrado)

    # ------------------------------------------------------------------

    def _editor_zoom_in_clicked(self):

        """Zoom + en el editor de páginas"""

        if self.editor_active and self.current_editor:

            self.current_editor.zoom_in()



    def _editor_zoom_out_clicked(self):

        """Zoom - en el editor de páginas"""

        if self.editor_active and self.current_editor:

            self.current_editor.zoom_out()



    def _toggle_editor_fit_mode(self):

        """Alterna entre hoja completa y ancho de ventana en el editor"""

        if self.editor_active and self.current_editor:

            self.current_editor.toggle_fit_mode()

            self._update_editor_fit_button()



    def _update_editor_fit_button(self):

        """Actualiza el icono del botón según el modo de vista actual"""

        if not hasattr(self, "btn_editor_fit"):

            return

        mode = getattr(self.current_editor, "fit_mode", "page") if self.current_editor else "page"

        if mode == "width":

            # Vista actual: ancho de ventana -> cuadrado con línea vertical

            # (mismo estilo "cuadrado" que ⛶, más grande/legible que ⇔)

            self.btn_editor_fit.configure(text="◫")

        else:

            # Vista actual: hoja completa

            self.btn_editor_fit.configure(text="⛶")

    

    def add_page_numbering(self, event=None):

        """Add page numbering to selected pages in the document (in memory)"""

        # En modo cajas no hay páginas expandidas en el visor, por eso bloqueamos
        # la autonumeración aquí y guiamos al usuario con un mensaje explícito.
        if self.grid.box_mode:

            messagebox.showwarning(

                "Modo cajas",

                "Primero necesitas Expandir (tecla Intro) y luego añadir la autonumeración."

            )

            return

        if not self.viewer.documents:

            messagebox.showwarning("Sin PDF", "No hay ningún PDF cargado")

            return



        # Check if numbering is already applied

        if hasattr(self, 'numbering_applied') and self.numbering_applied:

            messagebox.showwarning(

                "Numeración ya aplicada",

                "La numeración ya ha sido aplicada a este documento.\n\n"

                "Si deseas cambiarla, primero debes eliminar la numeración existente (Mayúsculas+T) o recargar el documento."

            )

            return

        

        # Get selected pages

        selected_pages = list(self.viewer.selected_pages)

        if not selected_pages:

            messagebox.showwarning(

                "Sin Selección",

                "No hay páginas seleccionadas.\n\n"

                "Selecciona las páginas que deseas numerar."

            )

            return

        

        # Filter out pages in "Borrados" section AND "Indice" section

        pages_to_number = []

        for page_idx in selected_pages:

            section = self.section_manager.get_section_at(page_idx)

            log.debug(f"Page {page_idx}: section={section.title if section else 'None'}, is_special={section.is_special if section else 'N/A'}")

            if section and not section.is_special:

                # Also exclude index section

                if section.title == self._INDEX_SECTION_TITLE:

                    log.debug(f"Skipping index section page {page_idx}")

                    continue

                pages_to_number.append(page_idx)

        

        log.info(f"Selected: {len(selected_pages)}, To number: {len(pages_to_number)}, Excluded: {len(selected_pages) - len(pages_to_number)}")

        

        if not pages_to_number:

            messagebox.showwarning(

                "Sin Páginas Válidas",

                "Las páginas seleccionadas están en la sección 'Borrados' o 'Indice'.\n\n"

                "Solo se pueden numerar páginas de secciones normales."

            )

            return

        

        # Show confirmation dialog
        excluded_count = len(selected_pages) - len(pages_to_number)
        excluded_msg = f"\n\n(Se excluirán {excluded_count} página(s) de secciones especiales/índice)" if excluded_count > 0 else ""
        
        result = messagebox.askyesno(
            "Añadir Numeración",
            f"Se añadirá numeración a {len(pages_to_number)} página(s) seleccionada(s).{excluded_msg}\n\n"
            f"Formato: {self.numbering_format}\n"
            f"Posición: {self.numbering_position}\n\n"
            f"La numeración se aplicará en memoria y se guardará cuando uses Mayúsculas+S.\n\n"
            f"¿Continuar?"
        )

        

        if not result:

            return

        

        # Show "Numerando..." dialog (same style as ProgressDialog)

        log.debug("Creating 'Numerando...' dialog")

        

        numbering_dialog = ctk.CTkToplevel(self.root)

        numbering_dialog.title("Numerando")

        numbering_dialog.geometry("400x150")

        numbering_dialog.resizable(False, False)

        numbering_dialog.transient(self.root)

        numbering_dialog.grab_set()

        numbering_dialog.bind("<Escape>", lambda e: numbering_dialog.destroy())

        numbering_dialog.update_idletasks()

        x = (numbering_dialog.winfo_screenwidth() // 2) - 200

        y = (numbering_dialog.winfo_screenheight() // 2) - 75

        numbering_dialog.geometry(f"400x150+{x}+{y}")

        

        # Message label (same style as ProgressDialog)

        ctk.CTkLabel(

            numbering_dialog, 

            text=f"Numerando {len(pages_to_number)} páginas...", 

            font=("Segoe UI", 11),

            wraplength=350

        ).pack(expand=True, pady=(30, 10))

        

        # Progress bar (indeterminate)

        progress_bar = ctk.CTkProgressBar(numbering_dialog, width=350, mode="indeterminate")

        progress_bar.pack(pady=(0, 30))

        progress_bar.start()

        

        numbering_dialog.update()

        log.debug("'Numerando...' dialog displayed")

        

        # Add numbering to document in memory

        self.update_status("Añadiendo numeración en memoria...")

        log.info(f"Adding page numbering to {len(pages_to_number)} selected pages (excluding Borrados and Indice)")

        

        try:

            current_doc = self.viewer.documents[0]

            doc = current_doc.doc  # fitz document

            

            # Use total of pages to number, not total selected

            total_to_number = len(pages_to_number)

            

            # Sort pages to get correct numbering order

            sorted_pages = sorted(pages_to_number)

            

            # Add numbering to selected pages only

            for idx, page_logical_idx in enumerate(sorted_pages):

                # Get actual page in document (pages may have been reordered)

                doc_idx, page_num_in_doc = self.viewer.pages[page_logical_idx]

                page = self.viewer.documents[doc_idx].doc[page_num_in_doc]

                

                # Format the page number text using current format

                # Use relative numbering within selection (1, 2, 3...) not absolute page numbers

                text = self.numbering_format.replace("%(n)", str(idx + 1))

                text = text.replace("%(N)", str(total_to_number))

                

                # Get page dimensions

                rect = page.rect

                page_width = rect.width

                page_height = rect.height

                

                # Calculate draw params respecting page rotation

                # Resolvemos posición y fuente con lógica anti-solape para posiciones inferiores.

                insert_rect, text_rotation, fontsize = self._resolve_numbering_draw_params(page, text)

                log.debug(

                    "Numbering page idx=%s (doc=%s page=%s) size=(%.1f x %.1f) rot=%s -> pos=(%.1f, %.1f) fontsize=%s text='%s'",

                    page_logical_idx,

                    doc_idx,

                    page_num_in_doc,

                    page_width,

                    page_height,

                    page.rotation,

                    insert_rect.x0,

                    insert_rect.y0,

                    fontsize,

                    text,

                )

                

                # Insertamos con fallback: si no cabe en la posición calculada,

                # reintentamos en la posición por defecto (bottom-center).

                rc, insert_rect, text_rotation, fontsize, used_default_fallback = self._insert_numbering_with_default_fallback(

                    page,

                    text,

                    insert_rect,

                    text_rotation,

                    fontsize,

                    context_label=f"page_idx={page_logical_idx}",

                )

                if rc < 0:

                    log.warning(

                        "Numbering not inserted on logical page %s (doc page %s): rc=%s, text='%s'",

                        page_logical_idx,

                        page_num_in_doc,

                        rc,

                        text,

                    )

                elif used_default_fallback:

                    log.info(

                        "Numbering inserted with default fallback on logical page %s (doc page %s): '%s' (rc=%.1f)",

                        page_logical_idx,

                        page_num_in_doc,

                        text,

                        rc,

                    )

                else:

                    log.debug(f"Added number to logical page {page_logical_idx} (doc page {page_num_in_doc}): '{text}' (rc={rc:.1f})")

            

            # Mark that numbering has been applied

            if not hasattr(self, 'numbering_applied'):

                self.numbering_applied = False

            self.numbering_applied = True

            

            # Clear thumbnail cache to force regeneration with numbering

            self.viewer.clear_cache()

            log.debug("Thumbnail cache cleared after adding numbering")

            

            # Clear grid image cache to force regeneration

            self.grid.clear_image_cache()

            log.debug("Grid image cache cleared after adding numbering")

            

            # Refresh thumbnails in grid to show the numbering

            self.grid.redraw()

            

            # If editor is active, refresh the current page

            if self.editor_active and self.current_editor:

                log.debug("Refreshing editor view after numbering")

                # Force reload of the current page in editor

                self.current_editor._load_page()

            

            # Update status and close dialog

            self.update_status(f"Numeración añadida ({len(selected_pages)} páginas) - Usa Mayúsculas+S para guardar")

            log.info(f"Page numbering added to {len(selected_pages)} selected pages in memory")

            numbering_dialog.destroy()

            

        except Exception as e:

            log.error(f"Error adding page numbering: {e}", exc_info=True)

            # Close dialog before showing error

            numbering_dialog.destroy()

            messagebox.showerror(

                "Error",

                f"No se pudo añadir la numeración:\n{e}"

            )

            self.update_status("Error al añadir numeración")



    def remove_page_numbering(self, event=None):

        """Remove page numbering from selected pages (Shift+T)"""

        if not self.viewer.documents:

            messagebox.showwarning("Sin PDF", "No hay ningún PDF cargado")

            return

        

        # Get selected pages

        selected_pages = list(self.viewer.selected_pages)

        if not selected_pages:

            messagebox.showwarning(

                "Sin Selección",

                "No hay páginas seleccionadas.\n\n"

                "Selecciona las páginas de las que deseas eliminar la numeración."

            )

            return

        

        # Filter out pages in "Borrados" section

        pages_to_clean = []

        for page_idx in selected_pages:

            section = self.section_manager.get_section_at(page_idx)

            if section and not section.is_special:

                # Also exclude index section

                if section.title == self._INDEX_SECTION_TITLE:

                    continue

                pages_to_clean.append(page_idx)

        

        if not pages_to_clean:

            messagebox.showwarning(

                "Sin Páginas Válidas",

                "Las páginas seleccionadas están en la sección 'Borrados' o 'Indice'.\n\n"

                "Solo se puede eliminar numeración de páginas de secciones normales."

            )

            return

        

        # Show confirmation dialog

        excluded_count = len(selected_pages) - len(pages_to_clean)

        excluded_msg = f"\n\n(Se excluirán {excluded_count} página(s) de secciones especiales/índice)" if excluded_count > 0 else ""

        

        result = messagebox.askyesno(

            "Eliminar Numeración",

            f"Se eliminará la numeración de {len(pages_to_clean)} página(s) seleccionada(s).{excluded_msg}\n\n"

            f"Esto borrará cualquier texto de numeración añadido previamente.\n\n"

            f"Este proceso puede tardar unos segundos. Paciencia...\n\n"

            f"¿Continuar?"

        )

        

        if not result:

            return

        

        # Show progress dialog

        log.debug("Creating 'Eliminando numeración...' dialog")

        

        removing_dialog = ctk.CTkToplevel(self.root)

        removing_dialog.title("Eliminando Numeración")

        removing_dialog.geometry("400x150")

        removing_dialog.resizable(False, False)

        removing_dialog.transient(self.root)

        removing_dialog.grab_set()

        removing_dialog.bind("<Escape>", lambda e: removing_dialog.destroy())

        removing_dialog.update_idletasks()

        x = (removing_dialog.winfo_screenwidth() // 2) - 200

        y = (removing_dialog.winfo_screenheight() // 2) - 75

        removing_dialog.geometry(f"400x150+{x}+{y}")

        

        ctk.CTkLabel(

            removing_dialog, 

            text=f"Eliminando numeración de {len(pages_to_clean)} páginas...\n\nEste proceso puede tardar unos segundos. Paciencia...", 

            font=("Segoe UI", 11),

            wraplength=350

        ).pack(expand=True, pady=(20, 8))

        

        progress_bar = ctk.CTkProgressBar(removing_dialog, width=350, mode="indeterminate")

        progress_bar.pack(pady=(0, 20))

        progress_bar.start()

        

        removing_dialog.update()

        log.debug("'Eliminando numeración...' dialog displayed")

        

        # Remove numbering from pages

        self.update_status("Eliminando numeración...")

        log.info(f"Removing page numbering from {len(pages_to_clean)} selected pages")

        

        try:

            removed_count = 0

            

            # Delegar la limpieza en el helper compartido
            removed_count = self._purge_numbering_from_pages(pages_to_clean)

            # Clear caches and refresh

            self.viewer.clear_cache()

            self.grid.clear_image_cache()

            self.grid.redraw()

            

            # Refresh editor if active

            if self.editor_active and self.current_editor:

                self.current_editor._load_page()

            

            # Update status and close dialog

            removing_dialog.destroy()

            

            # Reset numbering flag

            self.numbering_applied = False

            

            if removed_count > 0:

                self.update_status(f"Numeración eliminada de {len(pages_to_clean)} páginas")

                log.info(f"Removed numbering from {len(pages_to_clean)} pages ({removed_count} text items)")

            else:

                self.update_status(f"No se encontró numeración en las páginas seleccionadas")

                log.info(f"No numbering text found in {len(pages_to_clean)} pages")

                messagebox.showinfo(

                    "Sin Numeración",

                    "No se encontró texto de numeración en las páginas seleccionadas.\n\n"

                    "Asegúrate de que las páginas tienen numeración añadida previamente."

                )

            

        except Exception as e:

            log.error(f"Error removing page numbering: {e}", exc_info=True)

            removing_dialog.destroy()

            messagebox.showerror(

                "Error",

                f"No se pudo eliminar la numeración:\n{e}"

            )

            self.update_status("Error al eliminar numeración")

    

    def _purge_numbering_from_pages(self, page_indices):
        """Elimina físicamente la numeración de las páginas indicadas.

    Recorre cada página, busca texto de numeración en la zona configurada
    (position/margin/fontsize) y lo elimina con redactions. Devuelve el
    número de spans eliminados. No muestra diálogos ni resetea flags:
    es responsabilidad del llamador hacer la UI y el reset.
        """
        removed_count = 0
        pages_to_clean = list(page_indices)

        for page_logical_idx in pages_to_clean:


            # Get actual page in document

            doc_idx, page_num_in_doc = self.viewer.pages[page_logical_idx]

            page = self.viewer.documents[doc_idx].doc[page_num_in_doc]



            # Get page dimensions for numbering area detection

            rect = page.rect

            margin = self.numbering_margin

            fontsize = self.numbering_fontsize

            position = self.numbering_position or "bottom-center"



            # Define the area where numbering would be placed

            # We'll look for text in this region

            # Ampliamos la zona inferior para cubrir el nuevo layout con hueco lógico

            # del hueco configurable + desplazamiento anti-solape.

            footer_height = max(8.0, float(getattr(self, "numbering_footer_height_pt", 25)))

            bottom_extra_shift = self._get_effective_numbering_bottom_max_shift(page)

            search_height = max(fontsize * 3, footer_height + bottom_extra_shift + fontsize * 2)



            if "bottom" in position:

                # En bottom buscamos desde más arriba para capturar casos donde

                # la numeración se desplazó verticalmente para evitar solape.

                bottom_anchor = max(margin, footer_height)

                search_rect_visual = fitz.Rect(

                    0, max(0, rect.height - bottom_anchor - search_height),

                    rect.width, rect.height

                )

            elif "top" in position:

                search_rect_visual = fitz.Rect(

                    0, 0,

                    rect.width, margin + search_height

                )

            else:  # middle

                mid_y = rect.height / 2

                search_rect_visual = fitz.Rect(

                    0, mid_y - search_height,

                    rect.width, mid_y + search_height

                )



            # IMPORTANTE: `search_rect_visual` está en el sistema *visual* (page.rect).

            # Para páginas rotadas, necesitamos convertirlo a coordenadas PDF no rotadas

            # antes de usarlo como clip en `get_text`.

            search_rect = self._visual_rect_to_pdf_rect(page, search_rect_visual)



            # Get all drawings on the page

            drawings = page.get_drawings()

            items_to_remove = []



            # Find text items in the numbering area

            # PyMuPDF stores inserted text as drawings

            for i, drawing in enumerate(drawings):

                if drawing.get("type") == "text" or "items" in drawing:

                    # Check if drawing is in the numbering area

                    draw_rect = drawing.get("rect")

                    if draw_rect and search_rect.intersects(fitz.Rect(draw_rect)):

                        items_to_remove.append(i)



            # Alternative approach: Use redaction to remove text in the area

            # This is more reliable for removing inserted text

            text_instances = page.get_text("dict", clip=search_rect)



            if text_instances and "blocks" in text_instances:

                for block in text_instances["blocks"]:

                    if block.get("type") == 0:  # Text block

                        for line in block.get("lines", []):

                            for span in line.get("spans", []):

                                span_text = span.get("text", "")

                                # Check if this looks like numbering text

                                # Common patterns: "Página X de Y", "X/Y", "Pág. X", numbers

                                if self._is_numbering_text(span_text):

                                    span_rect = fitz.Rect(span["bbox"])

                                    # Add redaction annotation with transparent fill

                                    annot = page.add_redact_annot(span_rect)

                                    annot.set_colors(fill=[])

                                    annot.update()

                                    removed_count += 1

                                    log.debug(f"Marked for removal on page {page_logical_idx}: '{span_text}'")



            # Apply redactions (this removes the text)

            page.apply_redactions()



            log.debug(f"Processed page {page_logical_idx}")

        return removed_count

    def _is_numbering_text(self, text: str) -> bool:

        """Check if text looks like page numbering"""

        import re

        

        text = text.strip()

        if not text:

            return False

        

        # Common numbering patterns

        patterns = [

            r'^Página\s+\d+\s+de\s+\d+$',  # "Página X de Y"

            r'^Pág\.?\s*\d+\s*(de\s+\d+)?$',  # "Pág. X" or "Pág X de Y"

            r'^\d+\s*/\s*\d+$',  # "X/Y"

            r'^\d+\s+de\s+\d+$',  # "X de Y"

            r'^-\s*\d+\s*-$',  # "- X -"

            r'^\[\s*\d+\s*\]$',  # "[X]"

            r'^\(\s*\d+\s*\)$',  # "(X)"

            r'^Page\s+\d+\s+of\s+\d+$',  # "Page X of Y" (English)

        ]

        

        for pattern in patterns:

            if re.match(pattern, text, re.IGNORECASE):

                return True

        

        # Also check if it's just a number (common simple numbering)

        # But only if it's in the expected font size range (we can't check this here)

        # So we'll be more conservative and only match if it's a small number

        if re.match(r'^\d{1,4}$', text):

            return True

        

        return False



    def _visual_to_pdf_point(self, x: float, y: float, rotation: int, visual_width: float, visual_height: float):

        """Convierte un punto en coordenadas *visuales* (page.rect) a coordenadas PDF (sistema no rotado).



        PyMuPDF usa `page.rect` como caja *visual* (ya intercambiada cuando la página está rotada 90/270),

        pero muchos métodos (p.ej. `get_text(..., clip=...)`) esperan coordenadas en el sistema PDF no rotado.

        Esta conversión hace que el recorte (clip) coincida con la zona donde realmente se insertó la numeración.

        """

        rotation = int(rotation) % 360



        if rotation == 0:

            return x, y

        if rotation == 90:

            return y, visual_width - x

        if rotation == 180:

            return visual_width - x, visual_height - y

        if rotation == 270:

            return visual_height - y, x



        return x, y



    def _pdf_to_visual_point(self, x: float, y: float, rotation: int, visual_width: float, visual_height: float):

        """Convierte un punto en coordenadas PDF no rotadas a coordenadas visuales (page.rect)."""

        rotation = int(rotation) % 360

        if rotation == 0:

            return x, y

        if rotation == 90:

            return visual_width - y, x

        if rotation == 180:

            return visual_width - x, visual_height - y

        if rotation == 270:

            return y, visual_height - x

        return x, y



    def _pdf_rect_to_visual_rect(self, page: fitz.Page, pdf_rect: fitz.Rect) -> fitz.Rect:

        """Convierte un rectángulo PDF no rotado a un rectángulo visual (page.rect)."""

        rect = page.rect

        visual_width = rect.width

        visual_height = rect.height

        rotation = int(page.rotation) % 360

        # Convertimos las 4 esquinas para conservar correctamente los casos 90/270.

        points_pdf = [

            (pdf_rect.x0, pdf_rect.y0),

            (pdf_rect.x1, pdf_rect.y0),

            (pdf_rect.x0, pdf_rect.y1),

            (pdf_rect.x1, pdf_rect.y1),

        ]

        points_visual = [

            self._pdf_to_visual_point(x, y, rotation, visual_width, visual_height)

            for x, y in points_pdf

        ]

        xs = [p[0] for p in points_visual]

        ys = [p[1] for p in points_visual]

        return fitz.Rect(min(xs), min(ys), max(xs), max(ys))



    def _visual_rect_to_pdf_rect(self, page: fitz.Page, visual_rect: fitz.Rect) -> fitz.Rect:

        """Convierte un rectángulo definido en coordenadas *visuales* a un rectángulo en coordenadas PDF."""

        rect = page.rect

        visual_width = rect.width

        visual_height = rect.height

        rotation = int(page.rotation) % 360



        # Convertimos las 4 esquinas y construimos el bounding-box en el sistema no rotado.

        points_visual = [

            (visual_rect.x0, visual_rect.y0),

            (visual_rect.x1, visual_rect.y0),

            (visual_rect.x0, visual_rect.y1),

            (visual_rect.x1, visual_rect.y1),

        ]



        points_pdf = [

            self._visual_to_pdf_point(x, y, rotation, visual_width, visual_height)

            for x, y in points_visual

        ]

        xs = [p[0] for p in points_pdf]

        ys = [p[1] for p in points_pdf]



        return fitz.Rect(min(xs), min(ys), max(xs), max(ys))



    def _get_effective_numbering_bottom_max_shift(self, page: fitz.Page) -> float:

        """Devuelve el desplazamiento máximo efectivo para bottom-*, adaptado al alto de página."""

        configured_shift = max(0.0, float(getattr(self, "numbering_bottom_max_shift_pt", 0)))

        visual_height = max(1.0, float(page.rect.height))

        # Límite de seguridad para no colocar numeración demasiado arriba.

        max_upward_ratio = float(getattr(self, "numbering_bottom_max_upward_ratio", 0.40))

        max_upward_ratio = min(0.90, max(0.10, max_upward_ratio))

        ratio_capped_shift = visual_height * max_upward_ratio

        # Evita quedarnos cortos en páginas con pies documentales altos (CSV, códigos de barras, etc.).

        # Permitimos subir en páginas con pies complejos, pero respetando el tope porcentual.

        dynamic_shift = max(80.0, visual_height * 0.30)

        usable_shift = max(0.0, visual_height - 24.0)

        # Tope final: dentro de página y además sin sobrepasar el 40% inferior configurable.

        max_allowed_shift = min(usable_shift, ratio_capped_shift)

        return min(max_allowed_shift, max(configured_shift, dynamic_shift))



    def _inflate_rect_for_line_detection(self, rect: fitz.Rect, min_thickness: float = 1.2) -> fitz.Rect:

        """Expande rectángulos muy finos para detectar líneas horizontales/verticales."""

        # Algunos trazos vectoriales llegan con ancho o alto 0 y `intersects` no los detecta bien.

        rect = fitz.Rect(rect)

        min_thickness = max(0.2, float(min_thickness))

        half = min_thickness / 2.0

        x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1

        if abs(x1 - x0) < min_thickness:

            cx = (x0 + x1) / 2.0

            x0 = cx - half

            x1 = cx + half

        if abs(y1 - y0) < min_thickness:

            cy = (y0 + y1) / 2.0

            y0 = cy - half

            y1 = cy + half

        return fitz.Rect(x0, y0, x1, y1)



    def _get_visual_content_rects(self, page: fitz.Page, visual_rect: fitz.Rect):

        """Obtiene rectángulos visuales de contenido que caen dentro de una zona dada."""

        clip_rect = self._visual_rect_to_pdf_rect(page, visual_rect)

        page_area = max(1.0, page.rect.width * page.rect.height)

        content_rects = []

        text_data = page.get_text("dict", clip=clip_rect)

        if text_data and "blocks" in text_data:

            for block in text_data["blocks"]:

                block_type = block.get("type")

                if block_type == 0:

                    # Para texto usamos spans para que la colisión sea lo más precisa posible.

                    for line in block.get("lines", []):

                        for span in line.get("spans", []):

                            span_text = span.get("text", "")

                            span_bbox = span.get("bbox")

                            if not span_bbox or not span_text.strip():

                                continue

                            span_pdf_rect = self._inflate_rect_for_line_detection(fitz.Rect(span_bbox), min_thickness=0.8)

                            if not span_pdf_rect.intersects(clip_rect):

                                continue

                            span_visual_rect = self._pdf_rect_to_visual_rect(page, span_pdf_rect)

                            if span_visual_rect.intersects(visual_rect):

                                content_rects.append(span_visual_rect)

                    continue

                # Para imágenes/bloques no texto usamos el bbox del bloque completo.

                bbox = block.get("bbox")

                if not bbox:

                    continue

                block_pdf_rect = self._inflate_rect_for_line_detection(fitz.Rect(bbox), min_thickness=1.0)

                if not block_pdf_rect.intersects(clip_rect):

                    continue

                block_area = max(0.0, block_pdf_rect.width * block_pdf_rect.height)

                # Ignoramos fondos casi de página completa para evitar falsos positivos.

                if block_area >= page_area * 0.85:

                    continue

                block_visual_rect = self._pdf_rect_to_visual_rect(page, block_pdf_rect)

                if block_visual_rect.intersects(visual_rect):

                    content_rects.append(block_visual_rect)

        # También comprobamos dibujos vectoriales (líneas, cajas, tablas).

        for drawing in page.get_drawings():

            draw_rect = drawing.get("rect")

            if not draw_rect:

                continue

            # Expandimos trazos finos con el ancho declarado para detectar líneas de tablas/pies.

            stroke_width = float(drawing.get("width", 1.0) or 1.0)

            draw_pdf_rect = self._inflate_rect_for_line_detection(

                fitz.Rect(draw_rect),

                min_thickness=max(1.2, stroke_width + 0.8),

            )

            if not draw_pdf_rect.intersects(clip_rect):

                continue

            draw_area = max(0.0, draw_pdf_rect.width * draw_pdf_rect.height)

            if draw_area >= page_area * 0.85:

                continue

            draw_visual_rect = self._pdf_rect_to_visual_rect(page, draw_pdf_rect)

            if draw_visual_rect.intersects(visual_rect):

                content_rects.append(draw_visual_rect)

        return content_rects



    def _get_required_upward_shift_for_visual_rect(self, page: fitz.Page, visual_rect: fitz.Rect, padding: float = 3.0) -> float:

        """Calcula cuánto hay que subir un rectángulo para no solapar con contenido detectado."""

        required_shift = 0.0

        for content_rect in self._get_visual_content_rects(page, visual_rect):

            if not content_rect.intersects(visual_rect):

                continue

            # Subimos la caja justo por encima del borde superior del contenido (+padding).

            shift_for_this_rect = visual_rect.y1 - (content_rect.y0 - padding)

            if shift_for_this_rect > required_shift:

                required_shift = shift_for_this_rect

        return max(0.0, required_shift)



    def _visual_rect_has_content(self, page: fitz.Page, visual_rect: fitz.Rect) -> bool:

        """Comprueba si un rectángulo visual contiene contenido (texto/imagen/dibujo)."""

        return self._get_required_upward_shift_for_visual_rect(page, visual_rect) > 0



    def _insert_numbering_with_default_fallback(

        self,

        page: fitz.Page,

        text: str,

        insert_rect: fitz.Rect,

        text_rotation: int,

        fontsize: float,

        context_label: str = "",

    ):

        """Inserta numeración y, si falla, fuerza un fallback en bottom-center."""

        # Intento principal: posición calculada por el algoritmo anti-solape.

        rc = page.insert_textbox(

            insert_rect,

            text,

            fontname="helv",

            fontsize=fontsize,

            color=(0, 0, 0),

            align=fitz.TEXT_ALIGN_CENTER,

            rotate=text_rotation,

        )

        if rc >= 0:

            return rc, insert_rect, text_rotation, fontsize, False

        log.warning(

            "Primary numbering placement overflow (%s): rc=%s, rect=%s, fontsize=%s, text='%s'",

            context_label,

            rc,

            insert_rect,

            fontsize,

            text,

        )

        # Fallback pedido por usuario: posición por defecto en la parte inferior centrada.

        fallback_position = "bottom-center"

        fallback_footer_height = max(8.0, float(getattr(self, "numbering_footer_height_pt", 25)))

        min_fontsize = max(11, int(getattr(self, "numbering_min_fontsize", 11)))

        fallback_start_fontsize = max(min_fontsize, int(getattr(self, "numbering_bottom_start_fontsize", 15)))

        for fallback_fontsize in range(fallback_start_fontsize, min_fontsize - 1, -1):

            # Añadimos margen al ancho para minimizar nuevos overflows por redondeos tipográficos.

            fallback_text_width = fitz.get_text_length(text, fontname="helv", fontsize=fallback_fontsize) * 1.20

            fallback_rect, fallback_rotation = self._get_numbering_draw_params(

                page,

                fallback_text_width,

                fontsize_override=fallback_fontsize,

                position_override=fallback_position,

                bottom_shift_override=0.0,

                bottom_footer_height_override=fallback_footer_height,

            )

            rc_fallback = page.insert_textbox(

                fallback_rect,

                text,

                fontname="helv",

                fontsize=fallback_fontsize,

                color=(0, 0, 0),

                align=fitz.TEXT_ALIGN_CENTER,

                rotate=fallback_rotation,

            )

            if rc_fallback >= 0:

                return rc_fallback, fallback_rect, fallback_rotation, fallback_fontsize, True

        # Último recurso: franja inferior amplia centrada para no dejar la página sin numeración.

        rect = page.rect

        margin = max(0.0, float(self.numbering_margin))

        fallback_fontsize = float(min_fontsize)

        band_height = max(fallback_footer_height + fallback_fontsize * 2.2, fallback_fontsize * 3.0)

        fallback_visual_rect = fitz.Rect(

            0,

            max(0.0, rect.height - band_height - margin),

            rect.width,

            rect.height,

        )

        fallback_rect = self._visual_rect_to_pdf_rect(page, fallback_visual_rect)

        fallback_rotation = int(page.rotation) % 360

        rc_last = page.insert_textbox(

            fallback_rect,

            text,

            fontname="helv",

            fontsize=fallback_fontsize,

            color=(0, 0, 0),

            align=fitz.TEXT_ALIGN_CENTER,

            rotate=fallback_rotation,

        )

        return rc_last, fallback_rect, fallback_rotation, fallback_fontsize, True



    def _resolve_numbering_draw_params(self, page: fitz.Page, text: str):

        """Resuelve rectángulo/rotación/fuente final, evitando solapes en posiciones bottom-*."""

        position = self.numbering_position or "bottom-center"

        base_fontsize = max(6, int(self.numbering_fontsize))

        # Para top/middle mantenemos el comportamiento previo sin variaciones.

        if "bottom" not in position:

            text_width = fitz.get_text_length(text, fontname="helv", fontsize=base_fontsize)

            insert_rect, text_rotation = self._get_numbering_draw_params(

                page,

                text_width,

                fontsize_override=base_fontsize,

                position_override=position,

            )

            return insert_rect, text_rotation, base_fontsize

        # En posiciones bottom intentamos primero dentro de la banda lógica inferior.

        footer_height = max(8.0, float(getattr(self, "numbering_footer_height_pt", 25)))

        min_fontsize_cfg = int(getattr(self, "numbering_min_fontsize", 11))

        min_fontsize = max(11, min(base_fontsize, min_fontsize_cfg))

        max_shift = self._get_effective_numbering_bottom_max_shift(page)

        # Arrancamos alrededor de 15pt cuando sea posible, para mejorar legibilidad.

        preferred_start_fontsize = int(getattr(self, "numbering_bottom_start_fontsize", 15))

        preferred_start_fontsize = max(min_fontsize, preferred_start_fontsize)

        # Ajuste auxiliar según el tamaño del hueco inferior, manteniendo coherencia visual.

        footer_based_start = max(min_fontsize, int(round(max(float(min_fontsize), footer_height * 0.60))))

        start_fontsize = min(base_fontsize, max(preferred_start_fontsize, footer_based_start))

        shift_step = 2.0

        # Probamos fuente y desplazamiento hasta encontrar una zona sin texto.

        for fontsize in range(start_fontsize, min_fontsize - 1, -1):

            text_width = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)

            shift = 0.0

            while shift <= max_shift + 1e-6:

                insert_rect, text_rotation, visual_rect = self._get_numbering_draw_params(

                    page,

                    text_width,

                    fontsize_override=fontsize,

                    position_override=position,

                    bottom_shift_override=shift,

                    bottom_footer_height_override=footer_height,

                    return_visual_rect=True,

                )

                # Calculamos salto necesario para evitar líneas/tablas/texto detectados en la zona.

                required_shift = self._get_required_upward_shift_for_visual_rect(

                    page,

                    visual_rect,

                    padding=max(float(getattr(self, "numbering_content_clearance_pt", 4)), fontsize * 0.35),

                )

                if required_shift <= 0:

                    return insert_rect, text_rotation, fontsize

                # Avance adaptativo: subimos lo justo para salvar el obstáculo detectado.

                shift += max(shift_step, required_shift + 1.0)

        # Fallback: si no hay hueco dentro de la zona inferior permitida,

        # volvemos a la posición por defecto (bottom-center) con tamaño legible.

        fallback_fontsize = min(base_fontsize, max(min_fontsize, int(getattr(self, "numbering_bottom_start_fontsize", 15))))

        text_width = fitz.get_text_length(text, fontname="helv", fontsize=fallback_fontsize)

        insert_rect, text_rotation = self._get_numbering_draw_params(

            page,

            text_width,

            fontsize_override=fallback_fontsize,

            position_override="bottom-center",

            bottom_shift_override=0.0,

            bottom_footer_height_override=footer_height,

        )

        return insert_rect, text_rotation, fallback_fontsize



    def _get_numbering_draw_params(

        self,

        page: fitz.Page,

        text_width: float,

        fontsize_override: Optional[float] = None,

        position_override: Optional[str] = None,

        bottom_shift_override: float = 0.0,

        bottom_footer_height_override: Optional[float] = None,

        return_visual_rect: bool = False,

    ):

        """Return rectangle (fitz.Rect) and rotation so the text appears horizontal visually."""

        # page.rect in PyMuPDF reflects the *visual* dimensions (swapped if rotated 90/270)

        rect = page.rect

        visual_width = rect.width

        visual_height = rect.height

        rotation = int(page.rotation) % 360

        

        margin = max(0, self.numbering_margin)

        fontsize = float(self.numbering_fontsize if fontsize_override is None else fontsize_override)

        position = position_override or self.numbering_position or "bottom-center"

        footer_height = None

        shift_up = 0.0

        if bottom_footer_height_override is not None and "bottom" in position:

            # Guardamos parámetros del modo footer para usar caja compacta en posiciones bottom-*.

            footer_height = max(1.0, float(bottom_footer_height_override))

            shift_up = max(0.0, float(bottom_shift_override))

        

        rect_width = max(text_width + fontsize, fontsize * 4)

        # Si estamos en modo footer, usamos una caja más compacta para no invadir contenido.

        # En el resto de posiciones mantenemos la altura amplia existente.

        if footer_height is not None:

            # En el modo footer no forzamos el alto del hueco en la caja de texto, para permitir

            # encajar debajo de firmas/pies densos reduciendo fuente cuando haga falta.

            rect_height = max(fontsize * 1.9, fontsize + 4)

        else:

            # PyMuPDF insert_textbox needs height >= fontsize * 1.9 for text to fit.

            rect_height = max(fontsize * 2.0, fontsize + 20)

        

        # Determine center in visual coordinates

        if "left" in position:

            center_x = rect_width / 2 + margin

        elif "right" in position:

            center_x = visual_width - margin - rect_width / 2

        else:

            center_x = visual_width / 2

        

        if "top" in position:

            center_y = rect_height / 2 + margin

        elif "bottom" in position:

            if footer_height is not None:

                # En modo footer anclamos al hueco lógico inferior y aplicamos desplazamiento anti-solape.

                center_y = visual_height - (footer_height / 2) - shift_up

            else:

                # User requested to reduce space by half (margin / 2).

                center_y = visual_height - (margin / 2) - rect_height / 2

        else:

            center_y = visual_height / 2

        

        # Clamp centers so the rect stays within bounds

        half_w = rect_width / 2

        half_h = rect_height / 2

        center_x = min(max(center_x, half_w), max(half_w, visual_width - half_w))

        center_y = min(max(center_y, half_h), max(half_h, visual_height - half_h))

        # Conservamos también el rectángulo visual para poder comprobar colisiones de texto.

        visual_rect = fitz.Rect(

            center_x - half_w,

            center_y - half_h,

            center_x + half_w,

            center_y + half_h,

        )

        

        # Convert visual center to PDF coordinates (Unrotated system)

        # Note: In PyMuPDF, page.rect is the visual box.

        # But insert_textbox expects coordinates in the unrotated page system.

        # We need to map Visual(x,y) -> Unrotated(pdf_x, pdf_y)

        

        if rotation == 0:

            center_pdf_x, center_pdf_y = center_x, center_y

            pdf_rect_width, pdf_rect_height = rect_width, rect_height

            

        elif rotation == 90:

            # Visual Top-Left (0,0) is Unrotated (0, H_unrot) -> (0, visual_width)

            # Visual X axis -> Unrotated Y axis (Upwards: H_unrot - y)

            # Visual Y axis -> Unrotated X axis (Rightwards: x)

            # Unrotated X = Visual Y

            # Unrotated Y = Visual Width - Visual X

            center_pdf_x = center_y

            center_pdf_y = visual_width - center_x

            pdf_rect_width, pdf_rect_height = rect_height, rect_width

            

        elif rotation == 180:

            # Visual Top-Left (0,0) is Unrotated (W_unrot, H_unrot) -> (visual_width, visual_height)

            # Visual X axis -> Unrotated X axis (Leftwards: W_unrot - x)

            # Visual Y axis -> Unrotated Y axis (Upwards: H_unrot - y)

            center_pdf_x = visual_width - center_x

            center_pdf_y = visual_height - center_y

            pdf_rect_width, pdf_rect_height = rect_width, rect_height

            

        elif rotation == 270:

            # Visual Top-Left (0,0) is Unrotated (W_unrot, 0) -> (visual_height, 0)

            # Visual X axis -> Unrotated Y axis (Downwards: y)

            # Visual Y axis -> Unrotated X axis (Leftwards: W_unrot - x)

            # Unrotated X = Visual Height - Visual Y

            # Unrotated Y = Visual X

            center_pdf_x = visual_height - center_y

            center_pdf_y = center_x

            pdf_rect_width, pdf_rect_height = rect_height, rect_width

            

        else:

            center_pdf_x, center_pdf_y = center_x, center_y

            pdf_rect_width, pdf_rect_height = rect_width, rect_height

        

        x0 = center_pdf_x - pdf_rect_width / 2

        y0 = center_pdf_y - pdf_rect_height / 2

        insert_rect = fitz.Rect(x0, y0, x0 + pdf_rect_width, y0 + pdf_rect_height)

        

        # Text rotation: Counter-rotate to appear upright

        # PyMuPDF rotate is CCW. Page rotation is CW.

        # To align with visual horizontal, we need:

        # Page 90 CW -> Text 90 CCW (Bottom->Top unrotated) -> Visual Left->Right

        # Page 270 CW -> Text 270 CCW (Top->Bottom unrotated) -> Visual Left->Right

        text_rotation = rotation

        if return_visual_rect:

            return insert_rect, text_rotation, visual_rect

        return insert_rect, text_rotation



    def number_current_page(self, page_index: int):

        """Add numbering to a specific page (used by editor)"""

        try:

            if not self.viewer.documents:

                return

                

            current_doc = self.viewer.documents[0]

            doc = current_doc.doc

            total_pages = len(doc)

            

            if page_index < 0 or page_index >= total_pages:

                messagebox.showerror("Error", f"Índice de página inválido: {page_index}")

                return

            

            # Add numbering only to this page

            page = doc[page_index]

            

            # Format the page number text using current format

            text = self.numbering_format.replace("%(n)", str(page_index + 1))

            text = text.replace("%(N)", str(total_pages))

            

            # Get page dimensions

            rect = page.rect

            page_width = rect.width

            page_height = rect.height

            

            # Resolvemos posición y tamaño de fuente con la misma lógica que el foliado en lote.

            insert_rect, text_rotation, fontsize = self._resolve_numbering_draw_params(page, text)

            log.debug(

                "Numbering single page=%s size=(%.1f x %.1f) rot=%s -> pos=(%.1f, %.1f) fontsize=%s text='%s'",

                page_index,

                page_width,

                page_height,

                page.rotation,

                insert_rect.x0,

                insert_rect.y0,

                fontsize,

                text,

            )

            

            # Insertamos con la misma estrategia de fallback usada en el foliado por lote.

            rc, insert_rect, text_rotation, fontsize, used_default_fallback = self._insert_numbering_with_default_fallback(

                page,

                text,

                insert_rect,

                text_rotation,

                fontsize,

                context_label=f"single_page={page_index}",

            )

            if rc < 0:

                log.warning(f"Numbering could not be inserted on page {page_index + 1}: '{text}' (rc={rc})")

                self.update_status(f"No se pudo añadir numeración a página {page_index + 1}")

                return

            if used_default_fallback:

                log.info(f"Added numbering to page {page_index + 1} with default fallback: '{text}' (rc={rc:.1f})")

            else:

                log.info(f"Added numbering to page {page_index + 1}: '{text}'")

            

            # Clear caches and refresh

            self.viewer.clear_cache()

            self.grid.clear_image_cache()

            self.grid.redraw()

            

            # Refresh editor if active

            if self.editor_active and self.current_editor:

                self.current_editor._load_page()

            

            self.update_status(f"Numeración añadida a página {page_index + 1}")

            

        except Exception as e:

            log.error(f"Error numbering current page: {e}", exc_info=True)

            messagebox.showerror("Error", f"No se pudo añadir la numeración:\n{e}")

    

    def customize_numbering_format(self):

        """Show dialog to customize numbering format"""

        from tkinter import simpledialog

        

        # Show input dialog

        new_format = simpledialog.askstring(

            "Personalizar Formato",

            "Formato de numeración:\n\n"

            "%(n) = número de página actual\n"

            "%(N) = total de páginas\n\n"

            "Ejemplos:\n"

            "  'Página %(n) de %(N)'\n"

            "  '%(n)/%(N)'\n"

            "  'Pág. %(n)'\n",

            initialvalue=self.numbering_format,

            parent=self.root

        )

        

        if new_format:

            self.numbering_format = new_format

            log.info(f"Numbering format changed to: {new_format}")

            messagebox.showinfo(

                "Formato Actualizado",

                f"Nuevo formato: {new_format}\n\n"

                f"Se aplicará en las próximas numeraciones."

            )

    

    def change_numbering_position(self):

        """Show dialog to change numbering position"""

        # Create position selection dialog

        dialog = ctk.CTkToplevel(self.root)

        dialog.title("Cambiar Posición de Numeración")

        dialog.geometry("400x400")

        dialog.transient(self.root)

        dialog.grab_set()

        dialog.bind("<Escape>", lambda e: dialog.destroy())

        

        # Center dialog

        dialog.update_idletasks()

        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)

        y = (dialog.winfo_screenheight() // 2) - (400 // 2)

        dialog.geometry(f"400x400+{x}+{y}")

        

        # Title

        title_label = ctk.CTkLabel(

            dialog,

            text="Selecciona la posición de la numeración:",

            font=("Arial", 14, "bold")

        )

        title_label.pack(pady=20)

        

        # Position buttons

        positions = [

            ("Arriba Izquierda", "top-left"),

            ("Arriba Centro", "top-center"),

            ("Arriba Derecha", "top-right"),

            ("Abajo Izquierda", "bottom-left"),

            ("Abajo Centro", "bottom-center"),

            ("Abajo Derecha", "bottom-right"),

        ]

        

        selected_position = [self.numbering_position]  # Use list to modify in closure

        

        def select_position(pos):

            selected_position[0] = pos

            self.numbering_position = pos

            log.info(f"Numbering position changed to: {pos}")

            dialog.destroy()

            messagebox.showinfo(

                "Posición Actualizada",

                f"Nueva posición: {pos}\n\n"

                f"Se aplicará en las próximas numeraciones."

            )

        

        button_frame = ctk.CTkFrame(dialog)

        button_frame.pack(pady=10, padx=20, fill="both", expand=True)

        

        for label, pos in positions:

            btn = ctk.CTkButton(

                button_frame,

                text=label,

                command=lambda p=pos: select_position(p),

                fg_color="green" if pos == self.numbering_position else None

            )

            btn.pack(pady=5, padx=10, fill="x")

        

        # Cancel button

        cancel_btn = ctk.CTkButton(

            dialog,

            text="Cancelar",

            command=dialog.destroy

        )

        cancel_btn.pack(pady=10)

    

    def show_settings(self):

        """Show settings window"""

        from src.ui.settings_dialog import SettingsDialog

        SettingsDialog(

            self.root,

            self.config,

            ove_enabled=bool(self.extensions),

            show_advanced=bool(self.debug_mode),

            version_label=self.version_label,

            on_check_updates=self.check_for_updates_now,

        )

    

    def show_log_viewer(self):

        """Show log viewer window"""

        # Create log viewer window

        log_window = ctk.CTkToplevel(self.root)

        log_window.title("Visor de Log")

        

        # Center window relative to main window

        width = 800

        height = 600

        

        try:

            parent_x = self.root.winfo_x()

            parent_y = self.root.winfo_y()

            parent_width = self.root.winfo_width()

            parent_height = self.root.winfo_height()

            

            x = parent_x + (parent_width - width) // 2

            y = parent_y + (parent_height - height) // 2

            

            # Ensure not off-screen (basic check)

            if x < 0: x = 0

            if y < 0: y = 0

            

            log_window.geometry(f"{width}x{height}+{x}+{y}")

        except:

            # Fallback if geometry calc fails

            log_window.geometry(f"{width}x{height}")

        

        # Make it stay on top initially

        log_window.attributes('-topmost', True)

        log_window.after(100, lambda: log_window.attributes('-topmost', False))

        

        # Create text widget for log display

        log_frame = ctk.CTkFrame(log_window)

        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        

        # Text widget with scrollbar - adaptive colors

        import tkinter as tk

        mode = ctk.get_appearance_mode()

        log_bg = "#f5f5f5" if mode == "Light" else "#2b2b2b"

        log_fg = "#333333" if mode == "Light" else "#ffffff"

        text_widget = tk.Text(

            log_frame,

            wrap="word",

            bg=log_bg,

            fg=log_fg,

            font=("Consolas", 10),

            state="disabled"

        )

        scrollbar = tk.Scrollbar(log_frame, command=text_widget.yview)

        text_widget.config(yscrollcommand=scrollbar.set)

        

        scrollbar.pack(side="right", fill="y")

        text_widget.pack(side="left", fill="both", expand=True)

        

        # Get log content from logging handler

        import logging

        

        # Create a custom handler to capture logs

        class TextHandler(logging.Handler):

            def __init__(self, text_widget):

                super().__init__()

                self.text_widget = text_widget

                

            def emit(self, record):

                msg = self.format(record)

                self.text_widget.config(state="normal")

                self.text_widget.insert("end", msg + "\n")

                self.text_widget.see("end")

                self.text_widget.config(state="disabled")

        

        # Add handler to root logger

        text_handler = TextHandler(text_widget)

        text_handler.setFormatter(logging.Formatter(

            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        ))

        logging.getLogger().addHandler(text_handler)

        

        # Load existing logs from buffer

        text_widget.config(state="normal")

        text_widget.insert("1.0", "=== Visor de Log ===\n\n")

        

        # Insert all buffered logs

        if self.log_buffer:

            for log_msg in self.log_buffer:

                text_widget.insert("end", log_msg + "\n")

        else:

            text_widget.insert("end", "No hay mensajes de log todavía...\n\n")

        

        text_widget.see("end")  # Scroll to bottom

        text_widget.config(state="disabled")

        

        # Clean up handler when window closes

        def on_close():

            logging.getLogger().removeHandler(text_handler)

            log_window.destroy()

        

        log_window.protocol("WM_DELETE_WINDOW", on_close)

        

        # Buttons frame

        btn_frame = ctk.CTkFrame(log_window)

        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        

        # Clear button

        def clear_log():

            self.log_buffer.clear()

            text_widget.config(state="normal")

            text_widget.delete("1.0", "end")

            text_widget.insert("1.0", "=== Log limpiado ===\n\n")

            text_widget.config(state="disabled")

        

        clear_btn = ctk.CTkButton(

            btn_frame,

            text="Limpiar Log",

            command=clear_log,

            width=120,

            fg_color="#c0392b", 

            hover_color="#e74c3c"

        )

        clear_btn.pack(side="left", padx=5)



        # Guardar Log button

        def save_log():

            # Obtener el contenido del log

            content = text_widget.get("1.0", "end-1c")

            

            # Generar nombre de archivo con fecha/hora normalizado para Windows

            # Formato: Visor_Log_YYYY-MM-DD_HH-MM-SS.log

            from datetime import datetime

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

            default_filename = f"Visor_Log_{timestamp}.log"

            

            # Abrir diálogo de guardado

            with self._preserve_cwd():

                filepath = filedialog.asksaveasfilename(

                    parent=log_window,

                    title="Guardar Log",

                    defaultextension=".log",

                    initialfile=default_filename,

                    filetypes=[

                        ("Archivos de Log", "*.log"),

                        ("Archivos de Texto", "*.txt"),

                        ("Todos los archivos", "*.*")

                    ]

                )

            

            # Si el usuario seleccionó un archivo, guardarlo

            if filepath:

                try:

                    with open(filepath, 'w', encoding='utf-8') as f:

                        f.write(content)

                    log.info(f"Log guardado en: {filepath}")

                except Exception as e:

                    log.error(f"Error al guardar log: {e}")



        save_btn = ctk.CTkButton(

            btn_frame,

            text="Guardar Log",

            command=save_log,

            width=120

        )

        save_btn.pack(side="left", padx=5)

        

        # Close button

        close_btn = ctk.CTkButton(

            btn_frame,

            text="Cerrar",

            command=on_close,

            width=120

        )

        close_btn.pack(side="right", padx=5)



    def drop_files(self, event):

        """Handle dropped files"""

        try:

            # Parse file list (Tcl format: space separated, braces for paths with spaces)

            files = self.root.tk.splitlist(event.data)



            # Unificamos ingestión: filtrado/dedupe + conversiones (XML/imagen->PDF) en un solo punto.

            result = self.ingest_paths(files, source=IngestSource.DRAG_DROP)

            

            if result and result.get("added", 0) > 0:

                self.update_status(f"Cargados {result['added']} archivos arrastrados")

                

        except Exception as e:

            log.error(f"Error handling drop: {e}")



    def open_pdf(self):

        """Open file dialog for PDF/XML/image files."""

        # Cerrar el editor si está abierto: se van a cargar otros archivos

        self._close_editor_if_active()

        

        filetypes = [

            ("PDF, XML e imágenes", "*.pdf *.xml *.png *.jpg *.jpeg"),

            ("PDF files", "*.pdf"),

            ("XML files", "*.xml"),

            ("Image files", "*.png *.jpg *.jpeg"),

            ("All files", "*.*"),

        ]

        

        # Use last loaded directory as starting point

        initial_dir = self.config.get_last_loaded_dir()

        

        with self._preserve_cwd():

            filenames = filedialog.askopenfilenames(

                parent=self.root,

                title="Seleccionar archivos PDF/XML/imagen",

                filetypes=filetypes,

                initialdir=initial_dir

            )

        

        if filenames:

            self.ingest_paths(filenames, source=IngestSource.FILE_DIALOG)



    def _ensure_xml_conversion_temp_dir(self) -> Path:

        """Garantiza una carpeta temporal para conversiones de entrada a PDF."""

        if self.xml_conversion_temp_dir and os.path.exists(self.xml_conversion_temp_dir):

            return Path(self.xml_conversion_temp_dir)



        try:

            self.xml_conversion_temp_dir = tempfile.mkdtemp(prefix="podofilo_ingest_")

            log.info(f"Ingest conversion temp directory created: {self.xml_conversion_temp_dir}")

            return Path(self.xml_conversion_temp_dir)

        except OSError as e:

            # Logueamos contexto y relanzamos OSError con mensaje descriptivo.

            log_fs_error(log, e, "ensure_temp_dir[ingest_conversion]")

            raise OSError(f"[ingest_conversion] no se pudo crear el temp dir: {e!r}") from e



    def _convert_xml_to_temp_pdf(self, xml_path: Path) -> Path:

        """Convierte un XML local en un PDF A4 temporal para integrarlo en el flujo actual."""

        temp_dir = self._ensure_xml_conversion_temp_dir()



        # Mantenemos el nombre visible del XML en el PDF temporal (ej: fichero.xml.pdf).

        base_name = f"{xml_path.name}.pdf"

        candidate = temp_dir / base_name

        counter = 2

        while candidate.exists():

            candidate = temp_dir / f"{xml_path.name}_{counter}.pdf"

            counter += 1



        return convert_xml_file_to_pdf(xml_path=xml_path, output_pdf_path=candidate)



    def _convert_image_to_temp_pdf(self, image_path: Path) -> Path:

        """Convierte una imagen local (PNG/JPG/JPEG) en un PDF temporal para el flujo actual."""

        temp_dir = self._ensure_xml_conversion_temp_dir()



        # Mantenemos el nombre visible del fichero de imagen en el PDF temporal.

        base_name = f"{image_path.name}.pdf"

        candidate = temp_dir / base_name

        counter = 2

        while candidate.exists():

            candidate = temp_dir / f"{image_path.name}_{counter}.pdf"

            counter += 1



        return convert_image_file_to_pdf(image_path=image_path, output_pdf_path=candidate)



    def _ingest_skip_reason_to_text(self, reason: str) -> str:

        """Traduce los motivos técnicos de omisión a textos legibles para la UI."""

        reason_map = {

            # Ruta repetida en la misma carga: misma ruta absoluta, no solo mismo nombre.

            "duplicate": "Duplicado en esta carga (misma ruta ya incluida)",

            "not_found": "No existe o no es un archivo válido",

            "path_invalid": "Ruta inválida o no legible",

            "not_pdf": "No es PDF (tras normalización)",

            "xml_to_pdf_error": "Error al convertir XML a PDF",

            "image_to_pdf_error": "Error al convertir imagen a PDF",

        }

        return reason_map.get(reason, reason)



    def _show_ingest_skipped_dialog(self, summary: str, detail: str):

        """Muestra un diálogo con detalle desplazable y botón para copiar al portapapeles."""

        dialog = ctk.CTkToplevel(self.root)

        dialog.title("Archivos omitidos")

        width = 820

        height = 560

        dialog.geometry(f"{width}x{height}")

        dialog.minsize(680, 420)

        dialog.transient(self.root)

        dialog.grab_set()



        # Centramos el diálogo respecto a la ventana principal para mantener contexto visual.

        dialog.update_idletasks()

        try:

            x = self.root.winfo_x() + (self.root.winfo_width() - width) // 2

            y = self.root.winfo_y() + (self.root.winfo_height() - height) // 2

            if x < 0:

                x = 0

            if y < 0:

                y = 0

            dialog.geometry(f"{width}x{height}+{x}+{y}")

        except Exception:

            # Fallback seguro si por alguna razón no hay geometría padre disponible.

            dialog.geometry(f"{width}x{height}")



        content = ctk.CTkFrame(dialog, fg_color="transparent")

        content.pack(fill="both", expand=True, padx=14, pady=14)



        summary_label = ctk.CTkLabel(

            content,

            text=summary,

            justify="left",

            anchor="w",

            wraplength=780,

            font=("Segoe UI", 12),

        )

        summary_label.pack(fill="x", pady=(0, 10))



        text_frame = ctk.CTkFrame(content)

        text_frame.pack(fill="both", expand=True)



        # Widget de texto con scroll para que el usuario pueda revisar muchos omitidos.

        mode = ctk.get_appearance_mode()

        text_bg = "#f5f5f5" if mode == "Light" else "#2b2b2b"

        text_fg = "#333333" if mode == "Light" else "#ffffff"

        detail_text = tk.Text(

            text_frame,

            wrap="word",

            bg=text_bg,

            fg=text_fg,

            font=("Consolas", 10),

            state="normal",

        )

        detail_scroll = tk.Scrollbar(text_frame, command=detail_text.yview)

        detail_text.config(yscrollcommand=detail_scroll.set)

        detail_scroll.pack(side="right", fill="y")

        detail_text.pack(side="left", fill="both", expand=True)

        detail_text.insert("1.0", detail)

        detail_text.config(state="disabled")



        buttons = ctk.CTkFrame(content, fg_color="transparent")

        buttons.pack(fill="x", pady=(10, 0))



        def _copy_detail_to_clipboard():

            """Copia el resumen + detalle para pegar en tickets o incidencias."""

            to_copy = f"{summary}\n\n{detail}"

            try:

                self.root.clipboard_clear()

                self.root.clipboard_append(to_copy)

                self.root.update_idletasks()

                self.update_status("Detalle de archivos omitidos copiado al portapapeles")

            except Exception:

                self.update_status("No se pudo copiar el detalle de archivos omitidos")



        copy_btn = ctk.CTkButton(

            buttons,

            text="Copiar detalle",

            width=150,

            command=_copy_detail_to_clipboard,

        )

        copy_btn.pack(side="left")



        close_btn = ctk.CTkButton(

            buttons,

            text="Cerrar",

            width=120,

            command=dialog.destroy,

        )

        close_btn.pack(side="right")



        dialog.bind("<Escape>", lambda _event: dialog.destroy())



    def _notify_ingest_skipped_files(self, source: IngestSource, skipped: List[tuple[str, str]]):

        """Muestra una ventana con los archivos omitidos (nombre + motivo) en cargas interactivas."""

        if not skipped:

            return



        # Solo avisamos en acciones de usuario para no molestar en startup/watcher.

        interactive_sources = {

            IngestSource.FILE_DIALOG,

            IngestSource.DRAG_DROP,

            IngestSource.SINGLE_INSTANCE,

        }

        if source not in interactive_sources:

            return



        lines = []

        max_items = 20

        for raw_path, reason in skipped[:max_items]:

            raw_text = str(raw_path)

            try:

                name = Path(raw_text).name or raw_text

            except Exception:

                name = raw_text



            human_reason = self._ingest_skip_reason_to_text(reason)

            # Mostramos nombre + ruta para evitar ambigüedad cuando hay nombres iguales.

            lines.append(f"• {name}\n   Motivo: {human_reason}\n   Ruta: {raw_text}")



        remaining = len(skipped) - len(lines)

        if remaining > 0:

            lines.append(f"… y {remaining} archivo(s) más omitido(s).")



        summary = (

            f"Se omitieron {len(skipped)} archivo(s) durante la carga."

            "\n\nRevisa el detalle para saber exactamente cuál y por qué."

        )

        detail = "\n\n".join(lines)



        try:

            self._show_ingest_skipped_dialog(summary=summary, detail=detail)

        except Exception:

            # Si falla el diálogo, al menos dejamos trazabilidad en logs.

            log.warning("No se pudo mostrar aviso de archivos omitidos. Resumen: %s", summary)

            for line in lines:

                log.warning("Omitido -> %s", line.replace("\n", " | "))



    def ingest_paths(self, paths, source: IngestSource = IngestSource.UNKNOWN):

        """Entrada unificada para archivos locales (PDF/XML/imágenes).



        - Normaliza y filtra con `IngestPipeline`.

        - Mantiene el comportamiento actual: delega en `load_multiple_pdfs`.

        - Añade trazabilidad en `metadata['source']` por caja.



        Devuelve un dict simple para que los callers puedan mostrar estado (sin exponer clases internas).

        """



        # Preprocesado: convertimos entradas no-PDF soportadas (XML/imagen) a PDF temporal.

        # Así reutilizamos TODO el pipeline PDF existente sin bifurcar el flujo principal.

        prepared_paths = []

        pre_skipped: list[tuple[str, str]] = []

        xml_origin_map: Dict[str, str] = {}

        image_origin_map: Dict[str, str] = {}

        seen_source_paths: set[str] = set()

        last_real_input_dir: Optional[str] = None



        for raw_path in (paths or []):

            raw_str = str(raw_path)



            try:

                path_obj = Path(raw_path).expanduser()

            except Exception:

                # Mantenemos el valor original para que el pipeline etiquete path_invalid como hasta ahora.

                prepared_paths.append(raw_path)

                continue



            source_ext = path_obj.suffix.lower()

            if source_ext not in SUPPORTED_CONVERTIBLE_EXTENSIONS:

                prepared_paths.append(raw_path)



                # Guardamos carpeta real para no dejar la ruta temporal interna como "última carpeta".

                try:

                    resolved_non_xml = path_obj.resolve(strict=False)

                    if resolved_non_xml.exists() and resolved_non_xml.is_file():

                        last_real_input_dir = str(resolved_non_xml.parent)

                except Exception:

                    pass

                continue



            try:

                resolved_source = path_obj.resolve(strict=False)

            except Exception:

                resolved_source = path_obj



            if not resolved_source.exists() or not resolved_source.is_file():

                pre_skipped.append((raw_str, "not_found"))

                continue



            source_key = str(resolved_source)

            if source_key in seen_source_paths:

                pre_skipped.append((raw_str, "duplicate"))

                continue

            seen_source_paths.add(source_key)

            last_real_input_dir = str(resolved_source.parent)



            try:

                if source_ext == ".xml":

                    converted_pdf = self._convert_xml_to_temp_pdf(resolved_source)

                    xml_origin_map[str(converted_pdf)] = str(resolved_source)

                else:

                    converted_pdf = self._convert_image_to_temp_pdf(resolved_source)

                    image_origin_map[str(converted_pdf)] = str(resolved_source)

                prepared_paths.append(str(converted_pdf))

            except Exception as exc:

                if source_ext == ".xml":

                    log.error("No se pudo convertir XML a PDF (%s): %s", resolved_source, exc, exc_info=True)

                    pre_skipped.append((raw_str, "xml_to_pdf_error"))

                else:

                    log.error("No se pudo convertir imagen a PDF (%s): %s", resolved_source, exc, exc_info=True)

                    pre_skipped.append((raw_str, "image_to_pdf_error"))



        # Normalizar/filtrar PDFs a través del pipeline existente.

        result = self.ingest_pipeline.normalize_local_paths(source=source, paths=prepared_paths)

        combined_skipped = pre_skipped + [(s.raw, s.reason) for s in result.skipped]

        # Aviso visible en UI para que el usuario identifique rápidamente archivos omitidos.

        self._notify_ingest_skipped_files(source=source, skipped=combined_skipped)



        if not result.normalized_paths:

            return {

                "added": 0,

                "skipped": combined_skipped,

            }



        # Delegamos en la ruta existente (carga en modo cajas)

        self.load_multiple_pdfs([str(p) for p in result.normalized_paths])



        # Restituimos la última carpeta real de entrada para que el diálogo no apunte al temp interno.

        if last_real_input_dir:

            try:

                self.last_source_dir = last_real_input_dir

                self.config.set_last_loaded_dir(last_real_input_dir)

            except Exception:

                pass



        # Trazabilidad: intentamos marcar las cajas recién añadidas con su origen.

        # Nota: `LocalDocumentBox.__post_init__` fija metadata['source']='local'.

        # Con la opción A mantenemos `source` como tipo de caja (local/ove) y usamos `ingest_source`

        # como origen de entrada (drag_drop, watcher, startup, etc.).

        normalized_loaded_paths = {str(pp) for pp in result.normalized_paths}

        try:

            if getattr(self.grid, "box_mode", False):

                for box in (getattr(self.grid, "document_boxes", []) or []):

                    try:

                        if getattr(box, "metadata", None) is not None:

                            p = getattr(box, "file_path", None)

                            if p and str(p) in normalized_loaded_paths:

                                # Guardamos el valor estable (string) del Enum.

                                box.metadata["ingest_source"] = source.value



                                # Si el PDF viene de XML, guardamos la ruta original para trazabilidad.

                                xml_origin = xml_origin_map.get(str(p))

                                if xml_origin:

                                    box.metadata["original_xml_path"] = xml_origin



                                # Si el PDF viene de imagen, guardamos la ruta original para trazabilidad.

                                image_origin = image_origin_map.get(str(p))

                                if image_origin:

                                    box.metadata["original_image_path"] = image_origin

                    except Exception:

                        pass

        except Exception:

            pass



        return {

            "added": len(result.normalized_paths),

            "skipped": combined_skipped,

        }

    

    def load_multiple_pdfs(self, filepaths: list):

        """Load multiple PDFs using box mode (staging area)"""

        from src.pdf.structure import LocalDocumentBox, BoxState

        from pathlib import Path

        

        try:

            log.info(f"Loading {len(filepaths)} PDFs in box mode")

            

            # Update last loaded directory

            if filepaths:

                try:

                    folder = str(Path(filepaths[-1]).parent)

                    self.last_source_dir = folder

                    self.config.set_last_loaded_dir(folder)

                except: pass

            self.update_status(f"Cargando {len(filepaths)} archivos...")

            

            # Create document boxes for new files - initially QUEUED (not loading yet)

            new_boxes = []

            for filepath in filepaths:

                box = LocalDocumentBox(

                    name=Path(filepath).stem,

                    file_path=Path(filepath),

                    state=BoxState.QUEUED,  # Start as QUEUED, will change to LOADING when actually loading

                    progress=0.0

                )

                new_boxes.append(box)

            

            # Check if we're already in box mode - add to existing boxes

            if self.grid.box_mode:

                existing_boxes = self.grid.document_boxes.copy()

                all_boxes = existing_boxes + new_boxes

                self.grid.set_box_mode(all_boxes)

                start_index = len(existing_boxes)

            else:

                # If we have expanded pages, collapse them first to boxes

                if self.viewer.get_page_count() > 0:

                    # Enable collapse if we have sections

                    if self.section_manager.sections:

                        self._can_collapse_to_boxes = True

                        # IMPORTANTE (bug impresora/oviscapto):

                        # Cuando estamos en modo páginas y llega un nuevo PDF (watcher), colapsamos a cajas.

                        # Para poder re-expandir correctamente (y para que la precarga/warmup funcione),

                        # necesitamos conservar `file_path` de los documentos ya cargados.

                        #

                        # Antes se guardaba `file_path=None`, lo que hacía que la caja del documento previo

                        # no tuviera ruta y el warmup la ignorase. Resultado: al expandir, sólo quedaba el último.

                        #

                        # Solución: reconstruir el backup con rutas reales usando:

                        # - primero el backup anterior si existía

                        # - si no, deduciendo el doc_idx desde viewer.pages[section.start_page]

                        existing_backup_map = {}

                        try:

                            for b in (getattr(self, '_collapsed_boxes_backup', None) or []):

                                if isinstance(b, dict) and b.get('name') and b.get('file_path'):

                                    existing_backup_map[b['name']] = b.get('file_path')

                        except Exception:

                            existing_backup_map = {}



                        rebuilt_backup = []

                        for section in self.section_manager.get_saveable_sections():

                            resolved_path = None



                            # 1) Intentar reutilizar el backup anterior (título base sin sufijos /6p, etc.)

                            base_name = section.title.split('/')[0]

                            if base_name in existing_backup_map:

                                resolved_path = existing_backup_map.get(base_name)

                            elif section.title in existing_backup_map:

                                resolved_path = existing_backup_map.get(section.title)



                            # 2) Si no hay backup, deducir la ruta desde el viewer (doc_idx -> viewer.documents)

                            if not resolved_path:

                                try:

                                    if 0 <= section.start_page < len(self.viewer.pages):

                                        page_info = self.viewer.pages[section.start_page]

                                        if isinstance(page_info, tuple) and len(page_info) == 2:

                                            doc_idx, _page_num = page_info

                                            if 0 <= doc_idx < len(self.viewer.documents):

                                                resolved_path = getattr(self.viewer.documents[doc_idx], 'filepath', None)

                                except Exception:

                                    resolved_path = None



                            rebuilt_backup.append({

                                'name': section.title,

                                'file_path': resolved_path,

                                'page_count': section.page_count

                            })



                        self._collapsed_boxes_backup = rebuilt_backup

                    

                    if self._can_collapse_to_boxes:

                        self.collapse_to_boxes()

                        existing_boxes = self.grid.document_boxes.copy()

                        all_boxes = existing_boxes + new_boxes

                        self.grid.set_box_mode(all_boxes)

                        start_index = len(existing_boxes)

                    else:

                        # Shouldn't happen, but fallback to fresh start

                        self.grid.set_box_mode(new_boxes)

                        start_index = 0

                else:

                    # Fresh start - just use new boxes

                    self.grid.set_box_mode(new_boxes)

                    start_index = 0

            

            # Show expand button

            # El botón vive en self.footer_mode y debe respetar el orden derecha→izquierda

            self.btn_expand.pack(in_=self.footer_mode, side="right", padx=2, pady=2)

            # Hide collapse button if visible

            self.btn_collapse.pack_forget()

            

            # Schedule async loading AFTER UI has updated (shows all boxes as QUEUED first)

            # Small delay allows the UI to render the empty boxes before loading starts

            def start_loading():

                for i, box in enumerate(new_boxes):

                    self._load_pdf_to_box_async(box, start_index + i)

            

            self.root.after(50, start_loading)  # 50ms delay to let UI render first

            

            # Update status with total count

            total_boxes = len(self.grid.document_boxes)

            if total_boxes == 1:

                self.update_status("1 documento cargado")

            else:

                self.update_status(f"{total_boxes} documentos cargados")

            

        except Exception as e:

            log.error(f"Error loading multiple PDFs: {e}", exc_info=True)

            messagebox.showerror("Error", f"No se pudieron cargar los PDFs:\n{e}")

    

    def _load_pdf_to_box_async(self, box, box_index):

        """Load a PDF file into a box asynchronously with UI-safe updates"""

        from src.pdf.structure import BoxState

        import os

        import shutil

        import tempfile

        from pathlib import Path

        

        def update_ui_safe(callback):

            """Schedule UI update on main thread"""

            try:

                self.root.after(0, callback)

            except:

                pass

        

        def load_worker():

            temp_path = None

            try:

                # 1. Detect if it's a remote/network file

                file_path = str(box.file_path)

                is_remote = False

                if file_path.startswith("\\\\") or file_path.startswith("//"):

                    is_remote = True

                else:

                    try:

                        import ctypes

                        drive = os.path.splitdrive(os.path.abspath(file_path))[0]

                        if drive and ctypes.windll.kernel32.GetDriveTypeW(drive) == 4: # DRIVE_REMOTE

                            is_remote = True

                    except: pass



                # Acquire semaphore to limit concurrent loads

                with self._pdf_load_semaphore:

                    # Change state from QUEUED to LOADING

                    box.state = BoxState.LOADING

                    box.progress = 0.05

                    update_ui_safe(lambda: self.grid.update_box_state(box_index))

                    

                    # 2. If remote, copy to local temp first (shows progress)

                    actual_load_path = file_path

                    if is_remote:

                        try:

                            log.info(f"Copying remote file to local temp: {file_path}")

                            fd, temp_path = tempfile.mkstemp(suffix=".pdf", prefix="podofilo_remote_")

                            os.close(fd)

                            

                            filesize = os.path.getsize(file_path)

                            chunk_size = 1024 * 1024 # 1MB

                            bytes_copied = 0

                            

                            with open(file_path, 'rb') as fsrc:

                                with open(temp_path, 'wb') as fdst:

                                    while True:

                                        chunk = fsrc.read(chunk_size)

                                        if not chunk: break

                                        fdst.write(chunk)

                                        bytes_copied += len(chunk)

                                        # Progress from 0.05 to 0.40 during copy

                                        if filesize > 0:

                                            box.progress = 0.05 + (bytes_copied / filesize) * 0.35

                                            update_ui_safe(lambda: self.grid.update_box_state(box_index))

                            

                            actual_load_path = temp_path

                            log.info(f"Remote file local copy finished: {temp_path}")

                        except Exception as e_copy:

                            log.warning(f"Failed to copy remote file, will try direct open: {e_copy}")

                            actual_load_path = file_path



                    # 3. Load PDF using fitz para obtener info y thumbnail

                    box.progress = 0.45

                    update_ui_safe(lambda: self.grid.update_box_state(box_index))

                    

                    import fitz

                    doc = fitz.open(actual_load_path)

                    

                    box.progress = 0.6

                    update_ui_safe(lambda: self.grid.update_box_state(box_index))

                    

                    # Generar thumbnail de la primera página

                    thumbnail = None

                    page_count = len(doc)

                    if page_count > 0:

                        try:

                            pix = doc[0].get_pixmap(dpi=72)

                            from PIL import Image

                            thumbnail = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                        except Exception:

                            pass

                    

                    # --- INTEGRACION ANALISIS V2 (antes de cerrar doc) ---

                    try:

                        if page_count > 0:

                            page0 = doc[0]

                            text = page0.get_text()

                            rect = page0.rect

                            res = analisis.analizar_pagina(text, rect.width, rect.height)

                            

                            exp_encontrado = None

                            

                            # --- DETECCIÓN PATRÓN MASIVO (@@@expediente@@@nombre_doc@@@) ---

                            # Si el PDF contiene un código masivo, usamos su nombre_doc como

                            # nombre de la caja y su expediente como detectado (tiene prioridad

                            # porque es un marcador explícito insertado en el PDF).

                            # Además, se busca en las 3 primeras páginas (o menos si no existen)

                            # porque en algunos escritos el marcador no viene en la portada.

                            masivo = res.codigos_masivos[0] if res.codigos_masivos else None

                            masivo_page_idx = 0 if masivo else -1

                            if not masivo:

                                limite_paginas_masivo = min(page_count, 3)

                                for idx_masivo in range(1, limite_paginas_masivo):

                                    try:

                                        page_m = doc[idx_masivo]

                                        text_m = page_m.get_text()

                                        rect_m = page_m.rect

                                        res_m = analisis.analizar_pagina(text_m, rect_m.width, rect_m.height)

                                        if res_m.codigos_masivos:

                                            masivo = res_m.codigos_masivos[0]

                                            masivo_page_idx = idx_masivo

                                            break

                                    except Exception as e_masivo:

                                        log.debug(f"Error analizando patrón masivo en página {idx_masivo + 1}: {e_masivo}")

                            if masivo:

                                if masivo.nombre_doc:

                                    box.name = masivo.nombre_doc

                                    log.info(

                                        f"Patrón masivo detectado en página {masivo_page_idx + 1}: "

                                        f"caja renombrada a '{masivo.nombre_doc}'"

                                    )

                                if masivo.expediente:

                                    exp_encontrado = masivo.expediente

                                    log.info(

                                        f"Patrón masivo detectado en página {masivo_page_idx + 1}: "

                                        f"expediente detectado {masivo.expediente}"

                                    )

                            # ---------------------------------------------------------------

                            

                            # Fallback: buscar expediente por otros medios si el masivo no lo tenía

                            if not exp_encontrado and res.expedientes:

                                exp_encontrado = res.expedientes[0]

                            

                            if not exp_encontrado:

                                if res.codigos_tasa:

                                    for tasa in res.codigos_tasa:

                                        found = self.ove_service.buscar_por_tasa(tasa.referencia, tasa.cif_pasivo)

                                        if found:

                                            exp_encontrado = found

                                            break

                                if not exp_encontrado and res.codigos_correos:

                                    for codigo in res.codigos_correos:

                                        found = self.ove_service.buscar_por_correos(codigo)

                                        if found:

                                            exp_encontrado = found

                                            break

                            

                            if exp_encontrado:

                                box.metadata['expediente'] = exp_encontrado

                                # Propagar como expediente predeterminado global para diálogos OVE.

                                # Solo actualiza en memoria (se persistirá cuando el usuario lo use).

                                def _set_default_exp(exp=exp_encontrado):

                                    self.ove_last_expediente = exp

                                update_ui_safe(_set_default_exp)

                                

                    except Exception as e_ana:

                        log.error(f"Error in PDF Analysis for {box.name}: {e_ana}")

                    # -------------------------------

                    

                    # Cerrar el documento fitz (ya no lo necesitamos)

                    doc.close()

                    

                    # Crear PageReference para cada página (usando la ruta ORIGINAL, no temp)

                    # IMPORTANTE: Usamos file_path (ruta original) para que las referencias

                    # sean válidas incluso después de cerrar el documento fitz

                    page_refs = [

                        PageReference(file_path=str(box.file_path), page_index=i)

                        for i in range(page_count)

                    ]

                    

                    # Set internal state to LOADED con PageReference

                    box.set_loaded_refs(page_refs, thumbnail=thumbnail)

                    

                    # Update display - UI safe

                    update_ui_safe(lambda: self.grid.update_box_state(box_index))

                    

                    log.info(f"Loaded {box.name}: {len(page_refs)} pages as PageReference")

                

            except Exception as e:

                log.error(f"Error loading {box.name}: {e}", exc_info=True)

                box.set_failed(str(e))

                update_ui_safe(lambda: self.grid.update_box_state(box_index))

            finally:

                # Clean up local temp copy if created

                if temp_path and os.path.exists(temp_path):

                    try: os.remove(temp_path)

                    except: pass

                

                # Al terminar de cargar una caja, disparamos la precarga de la expansión

                update_ui_safe(self._trigger_expansion_warmup)

        

        # Run in thread

        thread = threading.Thread(target=load_worker, daemon=True)

        thread.start()

    

    def empty_trash(self):

        """Permanently delete all pages in 'Borrados' section"""

        deleted_section = None

        for s in self.section_manager.sections:

            if s.is_special and s.id == "deleted":

                deleted_section = s

                break

        

        if not deleted_section or deleted_section.page_count == 0:

            messagebox.showinfo("Papelera vacía", "No hay páginas en la papelera.")

            return



        if not messagebox.askyesno("Vaciar papelera", f"¿Estás seguro de eliminar definitivamente las {deleted_section.page_count} páginas de la papelera?"):

            return



        # self.add_undo_snapshot() # TODO: Undo support for empty trash



        # Determine indices to delete (from start_page to start_page + count)

        # Note: self.viewer.delete_pages takes a list of indices.

        # Since 'deleted' is always at the end (enforced by manager), indices are straightforward.

        start = deleted_section.start_page

        end = start + deleted_section.page_count

        to_delete = list(range(start, end))

        

        # Delete from viewer

        self.viewer.delete_pages(to_delete)

        

        # Reset deleted section

        deleted_section.page_count = 0

        deleted_section.start_page = self.viewer.get_page_count() # Should match new total

        

        # Refresh grid

        self._refresh_sections_after_delete()

        self.update_status("Papelera vaciada")



    # ============================================================

    # EXPANSION WARMUP (PRECARGA EN SEGUNDO PLANO)

    # ============================================================



    def _get_boxes_hash(self):

        """Genera un hash del estado actual de las cajas para invalidar la precarga si cambian."""

        if not hasattr(self.grid, 'document_boxes'):

            return 0

        items = []

        for box in self.grid.document_boxes:

            # Incluimos path, nombre y estado (usamos getattr porque RemoteDocumentBox no tiene file_path)

            path = str(getattr(box, 'file_path', ""))

            items.append((path, box.name, box.state))

        return hash(tuple(items))



    def _trigger_expansion_warmup(self, delay=1500):

        """Programa el inicio de la precarga tras un periodo de inactividad."""

        if not self.grid.box_mode:

            return

            

        if self._warmup_timer_id:

            self.root.after_cancel(self._warmup_timer_id)

            

        self._warmup_timer_id = self.root.after(delay, self._start_background_warmup)



    def _start_background_warmup(self):

        """Inicia el hilo de precarga si se cumplen las condiciones."""

        if not self.grid.box_mode or self._is_warmup_running:

            return

            

        # Verificar si hay cajas para expandir y si todas están listas

        from src.pdf.structure import BoxState

        valid_boxes = [box for box in self.grid.document_boxes 

                      if box.state == BoxState.LOADED]

        

        if not valid_boxes:

            return



        # IMPORTANTE: la precarga actual sólo sabe reconstruir expansión desde rutas (file_path).

        # Si hay cajas colapsadas (section_id) o cajas sin ruta, el warmup sería parcial y al

        # expandir podría “perder” documentos (como en el caso de impresora/oviscapto).

        # En ese escenario, desactivamos la precarga y dejamos que la expansión normal haga su trabajo.

        try:

            for box in self.grid.document_boxes:

                if getattr(box, 'metadata', None) and box.metadata.get('section_id'):

                    return

                if box.state == BoxState.LOADED and box.pages and not getattr(box, 'file_path', None):

                    return

        except Exception:

            # Si la comprobación falla, es más seguro no hacer warmup.

            return

            

        # Evitar precarga si hay cajas todavía en proceso de carga o pendientes de retry

        # IMPORTANTE: Incluir FAILED porque puede estar esperando auto-retry

        pending_states = (BoxState.QUEUED, BoxState.LOADING, BoxState.FAILED)

        if any(box.state in pending_states for box in self.grid.document_boxes):

            # Re-programar para más tarde

            self._trigger_expansion_warmup(1000)

            return



        # Si ya tenemos una precarga válida para este estado, no hacer nada

        current_hash = self._get_boxes_hash()

        if self._warmed_up_state and self._warmed_up_state['hash'] == current_hash:

            return

            

        # Limpiar precarga anterior si existía para este estado diferente (liberar archivos)

        if self._warmed_up_state:

            try: self._warmed_up_state['viewer'].close_all()

            except: pass

            self._warmed_up_state = None



        log.info("Iniciando precarga de expansión en segundo plano...")

        self._is_warmup_running = True

        thread = threading.Thread(target=self._warmup_worker, args=(current_hash,), daemon=True)

        thread.start()



    def _warmup_worker(self, current_hash):

        """Hilo de trabajo que realiza la carga de PDFs y generación de miniaturas."""

        try:

            from src.ui.pdf_viewer import PdfViewer

            from src.pdf.structure import Section, BoxState

            

            # Usar un viewer temporal para la precarga

            temp_viewer = PdfViewer()

            temp_sections = []

            current_page = 0

            

            # Usar una copia local de las cajas por seguridad de hilos

            boxes_to_process = list(self.grid.document_boxes)

            

            for box in boxes_to_process:

                # Si el usuario cambió de modo o alteró las cajas, abortar

                if not self.grid.box_mode or self._get_boxes_hash() != current_hash:

                    log.info("Precarga abortada: cambio detectado en las cajas.")

                    return

                

                if box.state != BoxState.LOADED:

                    continue

                

                try:

                    # Determinar cómo cargar la caja (fusionada vs individual)

                    added_pages = 0

                    

                    # NUEVO: Verificar primero si tiene page_refs (cajas fusionadas o con PageReference)

                    if box.page_refs and len(box.page_refs) > 0:

                        first_ref = box.page_refs[0]

                        

                        if isinstance(first_ref, PageReference):

                            # Cargar desde PageReference (cajas fusionadas o descargadas de OVE)

                            added_pages = temp_viewer.load_from_page_refs(box.page_refs)

                        elif isinstance(first_ref, tuple) and len(first_ref) == 2:

                            # Legacy format: tuplas (doc_idx, page_num)

                            # No podemos precargar este formato legacy sin el viewer principal

                            log.debug(f"Skipping warmup for legacy tuple format box: {box.name}")

                            continue

                        else:

                            # Formato desconocido - intentar file_path como fallback

                            path = getattr(box, 'file_path', None)

                            if path:

                                added_pages = temp_viewer.load_pdf(str(path))

                            else:

                                log.debug(f"Skipping warmup for box with unknown page format: {box.name}")

                                continue

                    

                    elif getattr(box, 'file_path', None):

                        # Cajas individuales con file_path

                        added_pages = temp_viewer.load_pdf(str(box.file_path))

                    

                    else:

                        # Sin páginas ni file_path - saltar

                        log.debug(f"Skipping warmup for box without pages or file_path: {box.name}")

                        continue

                    

                    section = Section(

                        id=f"box_{current_page}",

                        title=box.name,

                        start_page=current_page,

                        page_count=added_pages,

                        metadata=box.metadata.copy()

                    )

                    # Restaurar configuración de split si existe

                    if box.metadata.get('split_config'):

                        section.split_config = box.metadata.get('split_config')

                        

                    temp_sections.append(section)

                    

                    # Pre-renderizar algunas miniaturas por si el usuario mira rápido al expandir

                    # Calcular DPI basado en zoom actual

                    base_dpi = 72

                    scale_factor = self.grid.thumbnail_size / 150.0

                    dpi = int(base_dpi * scale_factor)

                    

                    # 5 miniaturas es suficiente para empezar

                    for i in range(min(5, added_pages)):

                        if self._get_boxes_hash() != current_hash: return

                        temp_viewer.get_page_thumbnail(current_page + i, dpi)

                        

                    current_page += added_pages

                    

                except Exception as e:

                    log.debug(f"Error en precarga de caja {box.name}: {e}")

            

            # Al final, guardar el estado precargado

            self._warmed_up_state = {

                'hash': current_hash,

                'viewer': temp_viewer,

                'sections': temp_sections

            }

            log.info(f"Precarga finalizada: {current_page} páginas listas.")

            

        except Exception as e:

            log.error(f"Error en worker de precarga: {e}")

        finally:

            self._is_warmup_running = False



    def expand_all_boxes(self):

        """Expand all document boxes into pages and sections with progress dialog"""

        from src.pdf.structure import BoxState, Section

        

        # Cerrar el editor si está abierto: la expansión cambia las páginas en vista

        self._close_editor_if_active()

        

        if not self.grid.box_mode:

            return

        

        # Contar boxes válidos para expandir

        valid_boxes = [box for box in self.grid.document_boxes 

                      if box.state == BoxState.LOADED and box.pages]

        

        if not valid_boxes:

            messagebox.showinfo("Info", "No hay documentos cargados para expandir")

            return

            

        # --- NUEVA LÓGICA DE EXPANSIÓN INSTANTÁNEA (PRECARGA) ---

        current_hash = self._get_boxes_hash()

        # Seguridad: si hay cajas colapsadas (section_id) o cajas expandibles sin file_path,

        # no podemos fiarnos de la precarga (puede ser parcial). Forzamos expansión normal.

        allow_warmup = True

        try:

            for box in valid_boxes:

                if getattr(box, 'metadata', None) and box.metadata.get('section_id'):

                    allow_warmup = False

                    break

                if box.state == BoxState.LOADED and box.pages and not getattr(box, 'file_path', None) and not box.metadata.get('merged_file_paths'):

                    allow_warmup = False

                    break

        except Exception:

            allow_warmup = False



        if allow_warmup and self._warmed_up_state and self._warmed_up_state['hash'] == current_hash:

            log.info("Usando expansión precargada para transición instantánea.")

            self.add_undo_snapshot()

            

            # Transferir datos del viewer precargado al viewer principal

            warmed_viewer = self._warmed_up_state['viewer']

            self.viewer.close_all() # Cerrar documentos actuales si los hubiera
            # El viewer precargado abre PDFs desde disco (sin numeración).
            # Reset defensivo del flag para permitir reaplicar T tras expandir.
            if getattr(self, 'numbering_applied', False):
                self.numbering_applied = False

            self.viewer.documents = warmed_viewer.documents

            self.viewer.pages = warmed_viewer.pages

            

            # Transferir secciones

            self.section_manager.sections = self._warmed_up_state['sections']

            

            # Restaurar Borrados si existen

            if hasattr(self, '_backend_deleted_pages') and self._backend_deleted_pages:

                 deleted_pages = self._backend_deleted_pages

                 self.viewer.pages.extend(deleted_pages)

                 start_deleted = sum(s.page_count for s in self.section_manager.sections)

                 del_section = Section(id="deleted", title="Borrados", start_page=start_deleted, 

                                     page_count=len(deleted_pages), is_special=True)

                 self.section_manager.sections.append(del_section)

                 self._backend_deleted_pages = []



            # Limpiar estado de precarga

            self._warmed_up_state = None

            

            # NUEVO: Verificar integridad de la expansión precargada

            verification_errors = []

            for i, box in enumerate(valid_boxes):

                if box.page_refs and len(box.page_refs) > 0:

                    expected_count = len(box.page_refs)

                    # Buscar la sección correspondiente a esta caja

                    if i < len(self.section_manager.sections):

                        section = self.section_manager.sections[i]

                        if section.page_count != expected_count:

                            error_msg = f"Error en '{box.name}': Se esperaban {expected_count} páginas, se cargaron {section.page_count}."

                            log.error(error_msg)

                            verification_errors.append(error_msg)

            

            # Mostrar advertencia si hubo errores de verificación

            if verification_errors:

                error_details = "\n".join(verification_errors)

                messagebox.showerror(

                    "Advertencia: Algo falló aquí", 

                    f"Se detectaron discrepancias durante la expansión:\n\n{error_details}\n\nEs posible que falten páginas."

                )

            

            # Ejecutar lógica de finalización de la expansión (UI)

            self._finalize_expansion_ui(valid_boxes)

            return

        # -------------------------------------------------------



        self.add_undo_snapshot()

        log.info(f"Expanding {len(valid_boxes)} boxes...")

        

        # Datos compartidos para el hilo

        expand_result = {

            "sections": [],

            "total_pages": 0,

            "error": None,

            "completed": False,

            "verification_errors": []

        }

        

        def expand_task(progress_dialog):

            """

            Tarea de expansión que se ejecuta en hilo separado.

            

            REFACTORIZADO: Ahora usa PageReference para cargar páginas de forma

            simple y consistente, sin necesidad de backups ni casos especiales.

            """

            try:

                import time

                

                # Reset del estado del viewer

                try:

                    self.viewer.close_all()

                except Exception:

                    self.viewer.documents = []

                    self.viewer.pages = []

                

                # close_all descarta cualquier fitz.Document numerado en RAM;

                # la numeración NO sobrevive a la reapertura desde disco.

                # Reset defensivo del flag para permitir reaplicar T tras expandir.

                if getattr(self, 'numbering_applied', False):

                    self.numbering_applied = False

                

                self.section_manager.sections = []

                

                current_page = 0

                total_boxes = len(valid_boxes)

                last_update_time = 0

                

                for idx, box in enumerate(valid_boxes):

                    if progress_dialog.is_cancelled:

                        log.info("Expansión cancelada por el usuario")

                        break

                    

                    # Actualizar progreso (limitado a ~10 FPS)

                    current_time = time.time()

                    if current_time - last_update_time > 0.1 or idx == 0 or idx == total_boxes - 1:

                        progress_dialog.update_progress(

                            (idx / total_boxes) * 0.7,

                            f"Cargando: {box.name}"

                        )

                        last_update_time = current_time

                    

                    added_pages = 0

                    split_config = box.metadata.get('split_config')

                    

                    # NUEVO: Verificar si las páginas son PageReference

                    if box.page_refs and len(box.page_refs) > 0:

                        first_ref = box.page_refs[0]

                        

                        if isinstance(first_ref, PageReference):

                            # CASO PRINCIPAL: Cargar desde PageReference (simple y consistente)

                            log.info(f"Expanding box '{box.name}' from {len(box.page_refs)} PageReferences")

                            added_pages = self.viewer.load_from_page_refs(box.page_refs)

                        

                        elif isinstance(first_ref, tuple) and len(first_ref) == 2:

                            # CASO LEGACY: Tuplas (doc_idx, page_num) - migrar a PageReference

                            log.warning(f"Box '{box.name}' uses legacy tuple format, attempting migration")

                            # Intentar cargar desde file_path si está disponible

                            path = getattr(box, 'file_path', None)

                            if path and Path(path).exists():

                                added_pages = self.viewer.load_pdf(str(path))

                            else:

                                log.error(f"Cannot expand legacy box '{box.name}': no file_path available")

                                continue

                        

                        elif hasattr(first_ref, 'get_pixmap'):

                            # CASO LEGACY: fitz.Page objects - cargar desde file_path

                            log.warning(f"Box '{box.name}' uses legacy fitz.Page format")

                            path = getattr(box, 'file_path', None)

                            if path and Path(path).exists():

                                added_pages = self.viewer.load_pdf(str(path))

                                # Cerrar el documento fitz de la caja

                                try:

                                    first_ref.parent.close()

                                except:

                                    pass

                            else:

                                log.error(f"Cannot expand legacy box '{box.name}': no file_path available")

                                continue

                        else:

                            log.error(f"Unknown page format in box '{box.name}': {type(first_ref)}")

                            continue

                    else:

                        # Sin páginas - intentar cargar desde file_path

                        path = getattr(box, 'file_path', None)

                        if path and Path(path).exists():

                            log.info(f"Expanding box '{box.name}' from file: {path}")

                            added_pages = self.viewer.load_pdf(str(path))

                        else:

                            log.warning(f"Box '{box.name}' has no pages and no file_path, skipping")

                            continue

                    

                    if added_pages == 0:

                        log.warning(f"Box '{box.name}' resulted in 0 pages, skipping")

                        continue

                    

                    # Create section for this document

                    section = Section(

                        id=f"box_{current_page}",

                        title=box.name,

                        start_page=current_page,

                        page_count=added_pages,

                        split_config=split_config,

                        metadata=box.metadata.copy()

                    )

                    self.section_manager.sections.append(section)

                    expand_result["sections"].append(section)

                    

                    current_page += added_pages

                    log.info(f"Expanded {box.name}: {added_pages} pages")

                    

                    # VERIFICACIÓN: Comprobar que se han cargado las páginas esperadas

                    # Especialmente crítico para cajas fusionadas que dependen de PageReference

                    if box.page_refs and len(box.page_refs) > 0:

                        expected_count = len(box.page_refs)

                        if added_pages != expected_count:

                            error_msg = f"Error en '{box.name}': Se esperaban {expected_count} páginas, se cargaron {added_pages}."

                            log.error(error_msg)

                            expand_result["verification_errors"].append(error_msg)

                

                expand_result["total_pages"] = current_page

                

                # --- RESTAURAR BORRADOS ---

                if hasattr(self, '_backend_deleted_pages') and self._backend_deleted_pages:

                     deleted_pages = self._backend_deleted_pages

                     log.info(f"Restoring {len(deleted_pages)} pages to Deleted section")

                     

                     # Añadir páginas al viewer

                     self.viewer.pages.extend(deleted_pages)

                     

                     # Crear sección Borrados

                     start_deleted = current_page

                     del_section = Section(

                         id="deleted",

                         title="Borrados",

                         start_page=start_deleted,

                         page_count=len(deleted_pages),

                         is_special=True

                     )

                     self.section_manager.sections.append(del_section)

                     

                     # Actualizar total páginas

                     current_page += len(deleted_pages)

                     expand_result["total_pages"] = current_page

                     

                     # Limpiar backup

                     self._backend_deleted_pages = []

                

                # Precargar miniaturas iniciales (30% restante)

                progress_dialog.update_progress(0.75, "Generando miniaturas...")

                

                # Precargar las primeras miniaturas para que aparezcan inmediatamente

                visible_count = min(20, current_page)  # Primeras 20 o menos

                for i in range(visible_count):

                    try:

                        self.viewer.get_page_thumbnail(i, dpi=72)

                        progress_dialog.update_progress(

                            0.75 + (i / visible_count) * 0.25,

                            f"Miniatura {i+1}/{visible_count}"

                        )

                    except:

                        pass

                

                progress_dialog.update_progress(1.0, "Completado")

                

            except Exception as e:

                expand_result["error"] = e

                log.error(f"Error expanding boxes: {e}", exc_info=True)

            

            expand_result["completed"] = True

            return expand_result

        

        # Mostrar diálogo de progreso (sin botón cancelar)

        dialog = ProgressDialog(

            self.root,

            "Expandiendo documentos",

            f"Expandiendo {len(valid_boxes)} documento(s)...",

            task=expand_task,

            cancellable=False

        )

        

        try:

            result = dialog.run_and_wait()

            

            if result and result.get("error"):

                messagebox.showerror("Error", f"Error al expandir:\n{result['error']}")

                return

            

            if result and result.get("completed"):

                # Verificar si hubo errores de integridad

                if result.get("verification_errors"):

                    error_details = "\n".join(result["verification_errors"])

                    messagebox.showerror(

                        "Advertencia: Algo falló aquí", 

                        f"Se detectaron discrepancias durante la expansión:\n\n{error_details}\n\nEs posible que falten páginas."

                    )

                

                self._finalize_expansion_ui(valid_boxes)

        except Exception as e:

            log.error(f"Error expanding boxes: {e}", exc_info=True)

            messagebox.showerror("Error", f"No se pudieron expandir los documentos:\n{e}")

    

    def _finalize_expansion_ui(self, valid_boxes):

        """Lógica común para finalizar la expansión y actualizar la interfaz."""

        try:

            # Save boxes for potential collapse back

            self._collapsed_boxes_backup = []

            for box in valid_boxes:

                self._collapsed_boxes_backup.append({

                    'name': box.name,

                    'file_path': box.file_path if hasattr(box, 'file_path') else None,

                    'page_count': len(box.pages) if box.pages else 0

                })

            self._can_collapse_to_boxes = True

            

            # Exit box mode

            self.grid.exit_box_mode()

            

            # Hide expand button, show collapse button

            self.btn_expand.pack_forget()

            # El botón vive en self.footer_mode y debe respetar el orden derecha→izquierda

            self.btn_collapse.pack(in_=self.footer_mode, side="right", padx=2, pady=2)

            

            # Clear selections

            self.grid.selected_indices.clear()

            if hasattr(self.viewer, 'selected_pages'):

                self.viewer.selected_pages.clear()

            

            # Update grid

            total_pages = self.viewer.get_page_count()

            actual_pages_len = len(self.viewer.pages)

            all_sizes = self.viewer.get_all_page_sizes()

            

            # VALIDACIÓN: Asegurar que el conteo es consistente

            if total_pages != actual_pages_len:

                log.warning(f"Page count mismatch! get_page_count()={total_pages}, len(pages)={actual_pages_len}")

                total_pages = actual_pages_len  # Usar el valor real

            

            log.info(f"Setting grid item_count={total_pages}, sizes_len={len(all_sizes)}")

            self.grid.set_item_count(total_pages, page_sizes=all_sizes)

            self.grid.set_sections(self.section_manager.sections)

            

            # Show loading dialog while preloading remaining thumbnails (only if many pages)

            num_boxes = len(valid_boxes)

            num_sections = len(self.section_manager.sections)

            

            if total_pages > 50:

                loading_dialog = ctk.CTkToplevel(self.root)

                loading_dialog.title("Expandiendo documentos")

                loading_dialog.geometry("400x150")

                loading_dialog.resizable(False, False)

                loading_dialog.transient(self.root)

                loading_dialog.grab_set()

                loading_dialog.bind("<Escape>", lambda e: loading_dialog.destroy())

                loading_dialog.update_idletasks()

                x = (loading_dialog.winfo_screenwidth() // 2) - 200

                y = (loading_dialog.winfo_screenheight() // 2) - 75

                loading_dialog.geometry(f"400x150+{x}+{y}")

                

                ctk.CTkLabel(loading_dialog, text=f"Cargando {total_pages} páginas...", font=("Segoe UI", 11)).pack(expand=True, pady=(30, 10))

                progress_bar = ctk.CTkProgressBar(loading_dialog, width=350, mode="indeterminate")

                progress_bar.pack(pady=(0, 30))

                progress_bar.start()

                loading_dialog.update()

            else:

                loading_dialog = None



            def on_preload_complete():

                self.grid.redraw()

                if loading_dialog: 

                    try: loading_dialog.destroy()

                    except: pass

                self.update_status(f"Expandidos {num_boxes} documentos ({total_pages} páginas)")

                log.info(f"Expansion complete: {total_pages} pages in {num_sections} sections")



            self._preload_thumbnails_progressive(on_complete=on_preload_complete)

            

            # Clear backup

            if hasattr(self, '_viewer_pages_backup'):

                self._viewer_pages_backup = None

                self._viewer_docs_backup = None

                

        except Exception as e:

            log.error(f"Error finalizing expansion UI: {e}", exc_info=True)

            messagebox.showerror("Error", f"Error al finalizar la expansión:\n{e}")



    def collapse_to_boxes(self):

        """

        Collapse expanded pages back to boxes (one box per section).

        This allows reordering entire sections as boxes before re-expanding.

        """

        from src.pdf.structure import LocalDocumentBox, BoxState

        

        # Cerrar el editor si está abierto: el colapso elimina la vista de páginas

        self._close_editor_if_active()

        

        if self.grid.box_mode:

            return  # Already in box mode

        

        if not self._can_collapse_to_boxes:

            return  # Nothing to collapse

        

        # --- AVISO DE PÉRDIDA DE NUMERACIÓN ---
        # Si se ha aplicado numeración en miniaturas, avisar al usuario de que al
        # expandir de nuevo desde modo Cajas se recargarán los PDFs originales desde
        # disco y la numeración se perderá. Se resetea el flag para que pueda reaplicar T.
        if getattr(self, 'numbering_applied', False):
            if not messagebox.askyesno(
                'Numeración de páginas',
                'Has aplicado numeración a las páginas.\n\n'
                'Si vuelves al modo Cajas y luego expands de nuevo, '
                'la numeración se perderá y tendrás que volver a aplicarla (tecla T).\n\n'
                '¿Quieres continuar y colapsar a modo Cajas?',
                icon='warning',
                default='no',
            ):
                self.update_status('Colapso cancelado: numeración conservada en miniaturas')
                return
            # Eliminar físicamente la numeración de las páginas de secciones
            # no especiales para que modo cajas y vista ampliada no la muestren
            # (coherencia con el aviso 'se perderá').
            purge_indices = []
            for sec in self.section_manager.sections:
                if sec.is_special:
                    continue
                if sec.title == self._INDEX_SECTION_TITLE:
                    continue
                purge_indices.extend(range(sec.start_page, sec.end_page))
            if purge_indices:
                self._purge_numbering_from_pages(purge_indices)
                self.viewer.clear_cache()
                self.grid.clear_image_cache()
            self.numbering_applied = False
            self.update_status('Numeración eliminada — podrá reaplicarla con T tras expandir')

        # --- PERSISTENCIA DE BORRADOS ---

        self._backend_deleted_pages = []

        deleted_sec = None

        for s in self.section_manager.sections:

            if s.id == "deleted" or s.is_special:

                 deleted_sec = s

                 break

        

        if deleted_sec and deleted_sec.page_count > 0:

            log.info(f"Persisting {deleted_sec.page_count} deleted pages before collapse")

            for page_idx in range(deleted_sec.start_page, deleted_sec.end_page):

                if page_idx < len(self.viewer.pages):

                    self._backend_deleted_pages.append(self.viewer.pages[page_idx])

        

        # Get current sections (excluding special sections like "Borrados")

        sections = self.section_manager.get_saveable_sections()

        

        if not sections:

            messagebox.showinfo("Info", "No hay secciones para colapsar")

            return

        

        self.add_undo_snapshot()

        log.info(f"Collapsing {len(sections)} sections to boxes...")

        

        # Rebuild boxes usando PageReference (inmutables y autocontenidas)

        new_boxes = self._rebuild_boxes_from_sections(sections)

        

        # NOTA: Ya no necesitamos backups de viewer.documents/pages porque

        # las cajas ahora usan PageReference que son autocontenidas.

        # Los backups legacy se mantienen temporalmente para compatibilidad.

        self._viewer_pages_backup = None

        self._viewer_docs_backup = None

        self._viewer_doc_paths_backup = None

        

        # Switch to box mode

        self.grid.set_box_mode(new_boxes)

        

        # Hide collapse button, show expand button

        self.btn_collapse.pack_forget()

        # El botón vive en self.footer_mode y debe respetar el orden derecha→izquierda

        self.btn_expand.pack(in_=self.footer_mode, side="right", padx=2, pady=2)

        

        # Update status

        self.update_status(f"Colapsadas {len(sections)} secciones a cajas - Reordena y pulsa INTRO para expandir")

        log.info(f"Collapsed to {len(new_boxes)} boxes")

    

    def _rebuild_boxes_from_sections(self, sections):

        """

        Helper to create Box objects from Sections usando PageReference.

        

        IMPORTANTE: Ahora usamos PageReference para que las referencias sean

        inmutables y no dependan del estado de viewer.documents.

        """

        from src.pdf.structure import LocalDocumentBox, BoxState

        

        new_boxes = []

        for section in sections:

            # Find the original file path for this section if available

            file_path = None

            if hasattr(self, '_collapsed_boxes_backup'):

                for backup in self._collapsed_boxes_backup:

                    if backup['name'] == section.title.split('/')[0]:  # Handle split configs

                        file_path = backup.get('file_path')

                        break

            

            # Create a box for this section

            box = LocalDocumentBox(

                name=section.title,

                file_path=file_path,

                state=BoxState.LOADED,

                progress=1.0

            )

            

            # Store section info in metadata for re-expansion

            box.metadata['section_id'] = section.id

            box.metadata['start_page'] = section.start_page

            box.metadata['page_count'] = section.page_count

            box.metadata['split_config'] = section.split_config

            

            # NUEVO: Crear PageReference para cada página de la sección

            # Esto garantiza que las referencias sean inmutables y autocontenidas

            page_refs = self.viewer.get_page_refs_for_range(section.start_page, section.end_page)

            box.page_refs = page_refs

            

            # Generate thumbnail from first page

            if section.start_page < self.viewer.get_page_count():

                try:

                    thumb = self.viewer.get_page_thumbnail(section.start_page, dpi=72)

                    box.thumbnail = thumb

                except Exception as e:

                    log.warning(f"Failed to generate thumb for rebuilt box {box.name}: {e}")    

            

            new_boxes.append(box)

        return new_boxes

    

    def merge_selected_boxes(self, event=None):

        """

        Fusionar las cajas seleccionadas en una sola.

        Las páginas de todas las cajas se combinan en orden de selección.

        

        REFACTORIZADO: Ahora usa PageReference para una fusión simple y consistente.

        Ya no hay casos especiales para tuplas vs fitz.Page.

        """

        from src.pdf.structure import LocalDocumentBox, BoxState

        

        if not self.grid.box_mode:

            return

        

        # Obtener índices seleccionados ordenados

        selected = sorted(self.grid.selected_indices)

        

        if len(selected) < 2:

            self.update_status("Selecciona al menos 2 cajas para fusionar")

            return

        

        # Obtener las cajas seleccionadas

        boxes_to_merge = [self.grid.document_boxes[i] for i in selected]

        

        # Verificar que todas estén cargadas

        for box in boxes_to_merge:

            if box.state != BoxState.LOADED:

                self.update_status(f"La caja '{box.name}' no está lista para fusionar")

                return

        

        self.add_undo_snapshot()

        log.info(f"Fusionando {len(boxes_to_merge)} cajas...")

        

        # Crear nombre para la caja fusionada

        merged_name = boxes_to_merge[0].name

        if len(boxes_to_merge) == 2:

            merged_name = f"{boxes_to_merge[0].name} + {boxes_to_merge[1].name}"

        else:

            merged_name = f"{boxes_to_merge[0].name} (+{len(boxes_to_merge)-1})"

        

        # NUEVO: Combinar PageReference de todas las cajas (simple y directo)

        merged_refs = []

        for box in boxes_to_merge:

            if box.page_refs:

                for ref in box.page_refs:

                    if isinstance(ref, PageReference):

                        merged_refs.append(ref)

                    else:

                        # Formato legacy - intentar convertir si hay file_path

                        log.warning(f"Box '{box.name}' has non-PageReference pages, skipping those")

        

        if not merged_refs:

            self.update_status("No hay páginas válidas para fusionar")

            return

        

        log.info(f"Merging {len(boxes_to_merge)} boxes: total {len(merged_refs)} PageReferences")

        

        # Crear la nueva caja fusionada

        merged_box = LocalDocumentBox(

            name=merged_name,

            file_path=getattr(boxes_to_merge[0], 'file_path', None),

            state=BoxState.LOADED,

            progress=1.0

        )

        merged_box.page_refs = merged_refs

        

        # Usar thumbnail del primer documento

        if boxes_to_merge[0].thumbnail:

            merged_box.thumbnail = boxes_to_merge[0].thumbnail

        

        # Metadata para identificar como fusionada (para mostrar ribbon)

        merged_box.metadata['merged_from'] = [box.name for box in boxes_to_merge]

        merged_box.metadata['merged_file_paths'] = ['__merged__']  # Marcador para ribbon visual

        

        # Insertar la caja fusionada en la posición del primer seleccionado

        insert_pos = selected[0]

        

        # Eliminar las cajas originales (de mayor a menor índice)

        for idx in reversed(selected):

            del self.grid.document_boxes[idx]

        

        # Insertar la nueva caja fusionada

        self.grid.document_boxes.insert(insert_pos, merged_box)

        

        # Actualizar tamaños y caches — respetando el zoom de cajas actual

        # (box_thumbnail_size) en vez de las constantes hardcodeadas 150x200,

        # que reseteaban el zoom a 100% tras una fusión.

        box_h = self.grid.box_thumbnail_size
        box_w = round(box_h * 0.75)
        self.grid.box_sizes = [(box_w, box_h) for _ in self.grid.document_boxes]

        self.grid.item_sizes = self.grid.box_sizes.copy()

        self.grid.aspect_ratios = [box_w / box_h for _ in self.grid.document_boxes]

        self.grid.item_count = len(self.grid.document_boxes)

        self.grid.box_images.clear()

        

        # Limpiar tracking de Smart Redraw

        self.grid._clear_all_drawn_items()

        

        # Actualizar selección a la nueva caja fusionada

        self.grid.selected_indices = {insert_pos}

        

        # Refrescar display

        self.grid._update_layout()

        self.grid.redraw()

        

        self.update_status(f"Fusionadas {len(boxes_to_merge)} cajas en '{merged_name}' ({len(merged_refs)} páginas)")

        log.info(f"Merged {len(boxes_to_merge)} boxes into '{merged_name}' with {len(merged_refs)} PageReferences")

    

    def load_pdf(self, filepath: str):

        """Load a single PDF file - delegates to load_multiple_pdfs for consistent behavior"""

        # Use the same logic as multiple PDFs for consistency

        self.load_multiple_pdfs([filepath])

    

    def _preload_thumbnails_async(self):

        """Preload low-res thumbnails in background for fast initial display"""

        def preload_worker():

            try:

                # Generate low-res thumbnails (72 DPI) for all pages

                # This populates the cache for fast rescaling later

                page_count = self.viewer.get_page_count()

                log.info(f"Preloading {page_count} thumbnails at 72 DPI...")

                

                for i in range(page_count):

                    try:

                        # Get low-res thumbnail (72 DPI)

                        self.viewer.get_page_thumbnail(i, dpi=72)

                    except Exception as e:

                        log.error(f"Error preloading page {i}: {e}")

                

                log.info("Thumbnail preload complete")

            except Exception as e:

                log.error(f"Error in preload worker: {e}")

        

        # Start preload in background thread

        thread = threading.Thread(target=preload_worker, daemon=True)

        thread.start()

    

    def _preload_thumbnails_progressive(self, on_complete=None):

        """

        Precarga progresiva de miniaturas:

        1. Primero carga las visibles (para scroll fluido inmediato)

        2. Luego carga el resto en segundo plano

        

        Args:

            on_complete: Optional callback to execute when preload is complete (called from main thread)

        """

        import time

        

        def preload_worker():

            try:

                page_count = self.viewer.get_page_count()

                if page_count == 0:

                    if on_complete:

                        self.root.after(0, on_complete)

                    return

                

                # Obtener rango visible actual

                visible_start, visible_end = self.grid.layout.get_visible_range(

                    int(self.grid.canvas.canvasy(0)),

                    self.grid.canvas.winfo_height()

                )

                

                # Expandir rango visible con buffer (páginas adyacentes)

                buffer_pages = 10

                priority_start = max(0, visible_start - buffer_pages)

                priority_end = min(page_count, visible_end + buffer_pages)

                

                log.info(f"Preloading thumbnails: visible [{visible_start}-{visible_end}], "

                        f"priority [{priority_start}-{priority_end}], total {page_count}")

                

                # Fase 1: Cargar páginas prioritarias (visibles + buffer)

                for i in range(priority_start, priority_end):

                    try:

                        self.viewer.get_page_thumbnail(i, dpi=72)

                    except Exception as e:

                        log.error(f"Error preloading priority page {i}: {e}")

                

                # Pequeña pausa para permitir que la UI responda

                time.sleep(0.05)

                

                # Fase 2: Cargar el resto en lotes pequeños

                remaining = []

                for i in range(page_count):

                    if i < priority_start or i >= priority_end:

                        remaining.append(i)

                

                batch_size = 5

                for batch_start in range(0, len(remaining), batch_size):

                    batch = remaining[batch_start:batch_start + batch_size]

                    for i in batch:

                        try:

                            self.viewer.get_page_thumbnail(i, dpi=72)

                        except Exception as e:

                            log.error(f"Error preloading page {i}: {e}")

                    

                    # Pequeña pausa entre lotes para no bloquear

                    time.sleep(0.01)

                

                log.info("Progressive thumbnail preload complete")

                

                # Call completion callback from main thread

                if on_complete:

                    self.root.after(0, on_complete)

                

            except Exception as e:

                log.error(f"Error in progressive preload worker: {e}")

                if on_complete:

                    self.root.after(0, on_complete)

        

        # Iniciar en hilo separado

        thread = threading.Thread(target=preload_worker, daemon=True)

        thread.start()



    def _show_easter_egg(self, event=None):

        """Easter egg oculto: muestra una imagen sorpresa encima de todo (Ctrl+Shift+F)"""

        try:

            # Resolver ruta de la imagen (compatible con PyInstaller y desarrollo)

            if getattr(sys, 'frozen', False):

                base_dir = Path(sys._MEIPASS)

            else:

                base_dir = Path(__file__).parent.parent.parent



            img_path = base_dir / "resources" / "others" / "fiuuu.jpg"

            if not img_path.exists():

                return "break"



            # Crear ventana toplevel sin bordes, siempre encima

            overlay = tk.Toplevel(self.root)

            overlay.overrideredirect(True)  # Sin barra de título ni bordes

            overlay.attributes("-topmost", True)  # Siempre encima de todo

            overlay.configure(bg="black")



            # Cargar imagen y escalarla para que ocupe la pantalla

            screen_w = self.root.winfo_screenwidth()

            screen_h = self.root.winfo_screenheight()

            pil_img = Image.open(str(img_path))



            # Escalar manteniendo proporción para que quepa entera (contain)

            img_ratio = pil_img.width / pil_img.height

            screen_ratio = screen_w / screen_h

            if img_ratio > screen_ratio:

                # Imagen más ancha que la pantalla: ajustar al ancho

                new_w = screen_w

                new_h = int(screen_w / img_ratio)

            else:

                # Imagen más alta que la pantalla: ajustar a la altura

                new_h = screen_h

                new_w = int(screen_h * img_ratio)

            pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)



            # Centrar la imagen en la pantalla

            tk_img = ImageTk.PhotoImage(pil_img)

            overlay.geometry(f"{screen_w}x{screen_h}+0+0")



            canvas = tk.Canvas(overlay, width=screen_w, height=screen_h,

                               bg="black", highlightthickness=0)

            canvas.pack(fill="both", expand=True)

            canvas.create_image(screen_w // 2, screen_h // 2,

                                image=tk_img, anchor="center")



            # Guardar referencia para evitar garbage collection

            overlay._tk_img = tk_img



            # Cerrar al hacer click o pulsar cualquier tecla

            overlay.bind("<Button-1>", lambda e: overlay.destroy())

            overlay.bind("<Key>", lambda e: overlay.destroy())

            overlay.focus_set()



            # Auto-cerrar después de 5 segundos por si acaso

            overlay.after(5000, lambda: overlay.destroy() if overlay.winfo_exists() else None)



        except Exception:

            pass  # Silencioso: es un easter egg, no debe romper nada

        return "break"



    def run(self):

        """Start application loop"""

        self.root.mainloop()

