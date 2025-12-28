"""
Main Window - CustomTkinter based UI
"""
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
import shutil
import tempfile
import sys
import fitz  # PyMuPDF
from collections import Counter

from src.ui.pdf_viewer import PdfViewer
from src.ui.virtual_grid import VirtualGrid
from src.ui.save_dialog import SaveDialog
from src.ui.dialogs import (
    CenteredInputDialog,
    SectionNamesEditorDialog,
    ProgressDialog,
    CenteredInputDialog,
    SectionNamesEditorDialog,
    ProgressDialog,
)
from src.ui.page_editor import PageEditorWindow
from src.pdf.structure import SectionManager, Section, LocalDocumentBox, BoxState, RemoteDocumentBox
from src.pdf.numbering import PdfNumbering
from src.utils.config import ConfigManager
from src.core.extension_loader import load_ove_extension

from src.ui.theme import get_theme, get_button_style, get_menu_icon
from src.core.watcher import WatcherManager
from src.core.single_instance import InstanceServer
import src.analysis.analisis as analisis

log = logging.getLogger(__name__)

class DnDApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)

class PodofiloApp:
    """Main application window"""
    
    def __init__(self, initial_files: Optional[List[Path]] = None, version_label: str = ""):
        """Initialize application"""
        log.info("Iniciando Podofilo V2...")
        
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
        
        # Numbering configuration
        # Numbering position config
        self.numbering_format = "Página %(n) de %(N)"
        self.numbering_position = "bottom-center"
        self.numbering_fontsize = 22
        self.numbering_margin = 30


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
        self.watcher_manager = WatcherManager(self._on_watched_file_detected)
        self._start_watchers()
        
        # Setup UI
        self._setup_ui()
        
        # Guardar rutas iniciales (filtradas a PDFs existentes)
        self._initial_files = []
        if initial_files:
            for file_path in initial_files:
                path = Path(file_path)
                if path.is_file() and path.suffix.lower() == ".pdf":
                    self._initial_files.append(path)
                else:
                    log.warning("Ruta inicial inválida o no es PDF: %s", path)

        if self._initial_files:
            self.root.after(200, self._open_initial_files)
        
        # Start Single Instance Server
        self.instance_server = InstanceServer(self._on_instance_message)
        self.instance_server.start()
        
        log.info("Application initialized")

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
            
            # 4. Cleanup Watcher Temp Dir
            if hasattr(self, 'watcher_temp_dir') and os.path.exists(self.watcher_temp_dir):
                try:
                    shutil.rmtree(self.watcher_temp_dir, ignore_errors=True)
                    log.info(f"Cleaned up watcher temp dir: {self.watcher_temp_dir}")
                except Exception as e:
                    log.warning(f"Error cleaning up watcher temp dir: {e}")
                
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
    
    def _on_instance_message(self, files: List[str]):
        """Handle files sent from another instance"""
        def process():
            # Focus window
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            
            if files:
                log.info(f"Cargando {len(files)} archivos desde otra instancia")
                self.load_multiple_pdfs(files)
        
        # Schedule to run on main thread
        self.root.after(0, process)
    
    def _open_initial_files(self):
        """Load PDF(s) passed at startup"""
        if not self._initial_files:
            return

        try:
            file_list = [str(path) for path in self._initial_files]
            if len(file_list) == 1:
                log.info("Abriendo PDF inicial: %s", file_list[0])
                self.load_pdf(file_list[0])
            else:
                log.info("Abriendo %d PDFs iniciales en modo caja", len(file_list))
                self.load_multiple_pdfs(file_list)
        except Exception as exc:
            log.error("No se pudieron abrir los PDFs iniciales: %s", exc, exc_info=True)
            messagebox.showerror(
                "Error", f"No se pudieron abrir los PDFs iniciales:\n{exc}"
            )
        finally:
            self._initial_files = []

    def _load_icons(self):
        """Load UI icons"""
        self.icons = {}
        icon_names = ["folder", "settings", "list", "box", "document", "cloud", "upload"]
        
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
                        size=(20, 20)
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
        """Update the shipment button color based on state (Semaphore)"""
        if not hasattr(self, "btn_shipments"):
            return
            
        theme = get_theme()
        
        # Default style (Ghost)
        new_fg = "transparent"
        new_hover = theme.BG_HOVER
        new_text = theme.TEXT_PRIMARY
        
        # Determine Color Logic (Priority: ERROR > SENDING > SUCCESS > IDLE)
        if n_errors > 0:
            # Red Semaphore (Error attention)
            new_fg = theme.ERROR
            new_hover = "#cc3030"
            new_text = "#ffffff"
        elif n_sending > 0 or n_wait > 0:
            # Blue Semaphore (Processing)
            new_fg = theme.BUTTON_PRIMARY_BG
            new_hover = theme.BUTTON_PRIMARY_HOVER
            new_text = theme.BUTTON_PRIMARY_TEXT
        elif n_done > 0 and n_done == total:
            # Green Semaphore (All successfully completed)
            new_fg = theme.SUCCESS
            new_hover = "#28a745" 
            new_text = "#ffffff"
            
        # Apply styles
        try:
            self.btn_shipments.configure(
                fg_color=new_fg,
                hover_color=new_hover,
                text_color=new_text
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
        
        # Asegurar que thumbnail_size está en un nivel válido
        self.thumbnail_size = self._snap_to_zoom_level(self.thumbnail_size)
        
        # Main content area (sin toolbar superior para maximizar espacio)
        self.content_frame = ctk.CTkFrame(self.root)
        self.content_frame.pack(side="top", fill="both", expand=True, padx=5, pady=5)
        
        # Virtual Grid
        self.grid = VirtualGrid(self.content_frame, ove_enabled=bool(self.extensions))
        self.grid.pack(fill="both", expand=True)
        # Establecer tamaño directamente (no llamar a set_thumbnail_size durante init)
        self.grid.thumbnail_size = self.thumbnail_size
        
        # Configure Grid Callbacks
        self.grid.on_request_image = self._on_request_image
        self.grid.on_selection_change = self._on_selection_change
        self.grid.on_right_click = self._on_right_click
        self.grid.on_click = self._on_thumbnail_click
        # The on_double_click is now passed in the constructor, so this line might be redundant or needs to be removed if the constructor takes precedence.
        # For now, keeping it as the user's snippet didn't explicitly remove it, but it's usually set once.
        # self.grid.on_double_click = self._on_thumbnail_double_click 
        self.grid.on_drag_start = self._on_drag_start
        self.grid.on_drag_motion = self._on_drag_motion
        self.grid.on_drag_end = self._on_drag_end
        self.grid.on_split_request = self.split_section_at
        self.grid.on_box_rename_request = self.rename_box
        self.grid.on_header_rename_request = self.rename_section
        self.grid.on_header_right_click = self._on_section_right_click
        
        # Pasar niveles de zoom para precarga inteligente
        self.grid._zoom_levels_for_preload = self.zoom_levels
        
        # Configure Sidebar Callbacks
        if hasattr(self.grid, 'sidebar'):
            self.grid.sidebar.on_section_click = self._on_section_click
            self.grid.sidebar.on_section_right_click = self._on_section_right_click
        
        # Restore continuous mode from config
        if self.config.get_continuous_mode():
            self.grid.set_continuous_mode(True)
            self.grid.sidebar.grid_remove()
        
        # Status bar con botones integrados
        self.status_bar = ctk.CTkFrame(self.root, height=35)
        self.status_bar.pack(side="bottom", fill="x", padx=5, pady=5)
        
        # Get theme for button styling
        theme = get_theme()
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
            width=40,
            height=30,
            font=("Segoe UI", 14),
            **ghost_btn_style
        )
        self.btn_open.pack(side="left", padx=2)

        # Status label (izquierda, después del botón)
        self.status_label = ctk.CTkLabel(
            self.status_bar,
            text="Listo - Abre un PDF para empezar",
            anchor="w",
            font=self.default_font
        )
        self.status_label.pack(side="left", padx=10, fill="x", expand=True)
        
        # Botones en el footer (derecha)
        # Orden visual deseado (Der -> Izq): OPCIONES | LOG | OVE | EXPANDIR/COLAPSAR
        # Packing order (Right -> Left): OPCIONES -> LOG -> OVE -> EXPANDIR/COLAPSAR
        
        self.btn_settings = ctk.CTkButton(
            self.status_bar,
            text="",
            image=self.icons.get("settings"),
            command=self.show_settings,
            width=40,
            height=30,
            font=("Segoe UI", 14),
            **ghost_btn_style
        )
        self.btn_settings.pack(side="right", padx=1)

        self.btn_log = ctk.CTkButton(
            self.status_bar,
            text="",
            image=self.icons.get("list"),
            command=self.show_log_viewer,
            width=40,
            height=30,
            font=("Segoe UI", 14),
            **ghost_btn_style
        )
        self.btn_log.pack(side="right", padx=1)

        self.btn_shipments = ctk.CTkButton(
            self.status_bar,
            text="",
            image=self.icons.get("upload"),
            command=self.show_shipment_window,
            width=40,
            height=30,
            font=("Segoe UI", 14),
            **ghost_btn_style
        )
        # self.btn_shipments.pack(side="right", padx=1) # Managed by _update_ove_button

        if self.extensions:
            self.btn_ove = ctk.CTkButton(
                self.status_bar,
                text="OVE",
                image=self.icons.get("cloud"),
                compound="right",
                command=self._on_ove_button_click,
                width=80,
                height=30,
                font=("Segoe UI", 11, "bold"),
                fg_color=theme.BUTTON_SECONDARY_BG,
                hover_color=theme.BUTTON_SECONDARY_HOVER,
                text_color=theme.BUTTON_SECONDARY_TEXT,
                border_width=1,
                border_color=theme.BUTTON_SECONDARY_BORDER
            )
            self.btn_ove.pack(side="right", padx=5)
        else:
            self.btn_ove = None

        # Botones expandir/colapsar se empaquetan dinámicamente (a la izquierda de OVE)
        self.btn_expand = ctk.CTkButton(
            self.status_bar,
            text=" EXPANDIR",
            image=self.icons.get("document"),
            compound="left",
            command=self.expand_all_boxes,
            height=30,
            font=("Segoe UI", 11),
            fg_color=theme.BUTTON_PRIMARY_BG,
            hover_color=theme.BUTTON_PRIMARY_HOVER,
            text_color=theme.BUTTON_PRIMARY_TEXT
        )
        
        self.btn_collapse = ctk.CTkButton(
            self.status_bar,
            text=" CAJAS",
            image=self.icons.get("box"),
            compound="left",
            command=self.collapse_to_boxes,
            height=30,
            font=("Segoe UI", 11),
            fg_color=theme.BUTTON_PRIMARY_BG,
            hover_color=theme.BUTTON_PRIMARY_HOVER,
            text_color=theme.BUTTON_PRIMARY_TEXT
        )
        
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
        self.root.bind("<Escape>", self.deactivate_cut_mode)
        self.root.bind_all("<Shift-S>", self.show_save_dialog)
        self.root.bind("<Control-a>", lambda e: self.open_pdf())
        self.root.bind("<Control-A>", lambda e: self.open_pdf())
        self.root.bind_all("<Control-s>", self._handle_ove_upload_shortcut)
        self.root.bind_all("<Control-S>", self._handle_ove_upload_shortcut)
        self.root.bind_all("<Shift-s>", self.show_save_dialog)
        self.root.bind("<Control-n>", self.clear_all)
        self.root.bind("<Control-N>", self.clear_all)
        
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
        self.root.bind("<Control-o>", self._handle_ove_shortcut)
        self.root.bind("<Control-O>", self._handle_ove_shortcut)

        # Undo/Redo
        self.root.bind("<Control-z>", self.undo)
        self.root.bind("<Control-Z>", self.undo)
        self.root.bind("<Control-y>", self.redo)
        self.root.bind("<Control-Y>", self.redo)
        
        # Continuous View Mode
        self.root.bind("<Alt-v>", self.toggle_continuous_mode)
        self.root.bind("<Alt-V>", self.toggle_continuous_mode)

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
        
        # Gestión de visibilidad del botón de Envíos
        if state == "connected":
            if not self.btn_shipments.winfo_ismapped():
                # Mostrar botón justo antes (a la derecha) de OVE
                # Al usar pack side=right, "before" significa a la derecha visualmente (procesado antes)
                self.btn_shipments.pack(side="right", padx=1, before=self.btn_ove)
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
                    delete_credentials(usuario)
                    err_msg = f"Error de conexión: {exc}"
                    self.root.after(0, lambda: self._on_ove_error(err_msg))
                    return
            finally:
                self.ove_thread = None

        self.ove_thread = threading.Thread(target=worker, daemon=True)
        self.ove_thread.start()

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

    def _handle_ove_upload_shortcut(self, event=None):
        """Maneja CTRL+S para subir documentos a OVE (con auto-conexión)"""
        if not self.extensions: return "break"
        
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
        # Dispatch to main thread
        self.root.after(0, lambda: self._handle_watched_file(file_path))

        def process_worker():
            try:
                # Actualizar directorio cargado (esto es rápido, se puede quedar aquí o ir al main thread)
                try:
                    folder = str(Path(file_path).parent)
                    self.root.after(0, lambda: self._update_last_dir(folder))
                except: pass
                
                target_path_local = file_path
                
                # Check auto-delete setting (Default behavior for watcher)
                if self.config.get_watch_auto_delete():
                    try:
                        # Preparar destino temporal
                        if not hasattr(self, 'watcher_temp_dir') or not os.path.exists(self.watcher_temp_dir):
                             self.watcher_temp_dir = tempfile.mkdtemp(prefix="podofilo_watch_")

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
                                        log.warning(f"Optimization OK but failed to delete original: {del_err}")
                                    log.info(f"File optimized and moved: {target_path_local}")
                                else:
                                    raise Exception("Optimized file is empty or missing")
                                    
                            except Exception as opt_err:
                                log.error(f"Optimization failed, falling back to simple move: {opt_err}")
                                # Fallback: simple move
                                if os.path.exists(target_path_local):
                                    try: os.remove(target_path_local)
                                    except: pass
                                import shutil
                                shutil.move(file_path, target_path_local)
                        else:
                            # Simple move (No optimization)
                            import shutil
                            shutil.move(file_path, target_path_local)
                            log.info(f"Moved watched file to temp (raw): {target_path_local}")
                        
                    except Exception as e:
                        log.error(f"Failed to move/auto-delete {file_path}: {e}")
                        target_path_local = file_path
                
                # Load the PDF (either original or temp) on Main Thread
                self.root.after(0, lambda: self.load_multiple_pdfs([target_path_local]))
                        
            except Exception as e:
                log.error(f"Error processing watched file {file_path}: {e}")
                self.root.after(0, lambda: self.update_status(f"Error importando {Path(file_path).name}"))

        # Launch processing in a dedicated background thread
        threading.Thread(target=process_worker, daemon=True).start()

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
                    'file_path': box.file_path, # Path object
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
                self.btn_expand.pack(side="right", padx=5, after=self.btn_ove)
            
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
                 self.btn_collapse.pack(side="right", padx=5, after=self.btn_ove)
            
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
            # ----------------------------------------
            
            # 3. Obtener tipos de firma si están disponibles
            tipos_firma = {}
            if self.ove_service and hasattr(self.ove_service, 'get_tipos_firma'):
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
                    tipos_firma=tipos_firma
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
                            # 1. Try physical path
                            fpath = getattr(box, 'file_path', None)
                            if not fpath and box.metadata and 'path' in box.metadata:
                                fpath = Path(box.metadata['path'])
                            
                            if fpath and Path(fpath).exists():
                                source_path = Path(fpath)
                            elif box.pages:
                                # 2. Fallback: generate from pages (e.g. collapsed box without save)
                                dest_path = Path(staging_dir) / safe_name
                                self.viewer.save_pages_direct(dest_path, box.pages, silent=True)
                                if dest_path.exists():
                                    source_path = dest_path
                                    temp_file_created = True
                                
                        elif item['type'] == 'section':
                            # Generate from pages
                            pages = item.get('pages', [])
                            if pages:
                                dest_path = Path(staging_dir) / safe_name
                                self.viewer.save_pages_direct(dest_path, pages, silent=True)
                                if dest_path.exists():
                                    source_path = dest_path
                                    temp_file_created = True
                        
                        # Add to Shipment Manager
                        if source_path and source_path.exists():
                            exp = item.get('expediente', '')
                            self.shipment_manager.add_shipment(exp, safe_name, source_path, 
                                                              tipo_firma=item.get('tipo_firma'),
                                                              tipo_firma_metadata=item.get('tipo_firma_metadata'))
                        else:
                            log.error(f"Could not prepare source for {safe_name}")
                            
                    except Exception as e:
                        log.error(f"Error processing item {safe_name}: {e}")
            
            finally:
                try:
                    shutil.rmtree(staging_dir)
                except:
                    pass
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
                "Número de Expediente (puedes usar formato abreviado, ej: 251234)",
                initial_value=self.ove_last_expediente or "",
            )
            value = dialog.get_input()
            if value is None:
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
                         self.ove_service = OVEUnificadoService()
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
                    delete_credentials(usuario)
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
                    self.ove_service.descargar_documentos(documentos, progreso=progreso)
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
                box.file_path = path
                box.metadata["path"] = str(path)
                try:
                    doc_pdf = fitz.open(str(path))
                    # box.metadata["doc"] = doc_pdf  <-- REMOVED: Cannot pickle fitz.Document
                    pages = [doc_pdf[i] for i in range(len(doc_pdf))]
                    box.pages = pages
                    if pages:
                        box.thumbnail = pages[0]
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
                box.file_path = path
                box.metadata["path"] = str(path)
                try:
                    doc_pdf = fitz.open(str(path))
                    # box.metadata["doc"] = doc_pdf  # REMOVED: Cannot pickle fitz.Document
                    pages = [doc_pdf[i] for i in range(len(doc_pdf))]
                    box.pages = pages
                    if pages:
                        box.thumbnail = pages[0]
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
            self.btn_expand.pack(side="right", padx=5, after=self.btn_ove)



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

        # Extract docs for the service
        docs_to_download = []
        box_map = {} # doc.id -> (box, index)
        
        for box, index in batch:
            doc = box.metadata.get("document")
            if doc:
                docs_to_download.append(doc)
                box_map[doc.id] = (box, index)
                
                # Set to Loading
                box.state = BoxState.LOADING
                box.progress = 0.0
                self.grid.update_box_state(index)

        if not docs_to_download:
            return

        self.update_status(f"Reintentando {len(docs_to_download)} documentos...")

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
                
                # Helper to update progress for specific boxes
                self.ove_service.descargar_documentos(docs_to_download, progreso=progreso)
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
                
                self.ove_service.descargar_documentos([doc_info], progreso=progreso)
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
        
    def clear_all(self, event=None):
        """Clear all content (Reset application)"""
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
        
        self.update_status("Listo - Abre un PDF para empezar")
        self.update_title()
        
        # Reset numbering flag
        self.numbering_applied = False
        
        log.info("Application cleared")

    def _on_request_image(self, index: int, size: int) -> Image.Image:
        """Callback to fetch image for grid"""
        try:
            # In box mode, don't try to get page thumbnails
            if self.grid.box_mode:
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
        except Exception as e:
            # In box mode, this is expected (no pages loaded yet)
            if self.grid.box_mode:
                log.debug(f"Skipping image request in box mode: {index}")
            else:
                log.warning(f"Invalid page index: {index}")
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
                command=self.open_page_editor,
                image=icons["edit"],
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
                    label="Abrir Lector Externo",
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
            menu.add_separator()
            if self.extensions:
                menu.add_command(
                    label="Subir Expediente al OVE",
                    accelerator="(Ctrl + S)",
                    command=self._handle_ove_upload_shortcut,
                    image=icons["upload"],
                    compound="left"
                )
                
                menu.add_command(
                    label="Descargar Expediente OVE",
                    accelerator="(Ctrl + O)",
                    command=self._trigger_ove_download,
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
            return
        
        # Check if there are pages loaded
        has_pages = self.viewer.get_page_count() > 0
        has_selection = len(self.viewer.selected_pages) > 0
        has_marked = len(self.viewer.marked_pages) > 0
        has_undo = bool(self.undo_stack)
        has_redo = bool(self.redo_stack)
        can_split = index != -1 and has_pages
        
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
        
        # Page operations (require selection or pages)
        menu.add_command(
            label="Duplicar páginas",
            accelerator="(D)",
            command=self.duplicate_selected,
            state="normal" if has_selection else "disabled",
            image=icons["duplicate"] if has_selection else icons["duplicate_dim"],
            compound="left"
        )
        menu.add_command(
            label="Añadir páginas en blanco",
            accelerator="(Mayúsculas + D)",
            command=self.insert_blank_pages,
            state="normal" if has_pages else "disabled",
            image=icons["blank"] if has_pages else icons["blank_dim"],
            compound="left"
        )
        menu.add_command(
            label="Eliminar páginas",
            accelerator="(Supr)",
            command=self.delete_selected,
            state="normal" if has_selection else "disabled",
            image=icons["delete"] if has_selection else icons["delete_dim"],
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
        
        menu.add_separator()
        
        # Rotation
        menu.add_command(
            label="Girar páginas hacia la derecha",
            accelerator="(Ctrl + R)",
            command=self.rotate_selected,
            state="normal" if has_selection else "disabled",
            image=icons["rotate"] if has_selection else icons["rotate_dim"],
            compound="left"
        )
        
        menu.add_separator()
        
        # Blank page marking
        menu.add_command(
            label="Marcar páginas en blanco",
            accelerator="(B)",
            command=self.mark_selected_blank,
            state="normal" if has_selection else "disabled",
            image=icons["mark"] if has_selection else icons["mark_dim"],
            compound="left"
        )
        menu.add_command(
            label="Desmarcar páginas",
            accelerator="(Mayúsculas + B)",
            command=self.unmark_selected,
            state="normal" if has_selection else "disabled",
            image=icons["unmark"] if has_selection else icons["unmark_dim"],
            compound="left"
        )
        menu.add_command(
            label="Borrar páginas marcadas",
            accelerator="(X)",
            command=self.delete_marked,
            state="normal" if has_marked else "disabled",
            image=icons["delete"] if has_marked else icons["delete_dim"],
            compound="left"
        )
        
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
        
        # Section operations (only if clicking on a valid page)
        menu.add_command(
            label="Dividir Sección Aquí",
            command=lambda: self.split_section(index),
            state="normal" if can_split else "disabled",
            image=icons["split"] if can_split else icons["split_dim"],
            compound="left"
        )
        
        
        if self.extensions:
            menu.add_separator()
            menu.add_command(
                label="Subir al Expediente OVE",
                accelerator="(Ctrl + S)",
                command=self._handle_ove_upload_shortcut,
                image=icons["upload"],
                compound="left"
            )
            menu.add_command(
                label="Descargar Expediente OVE",
                accelerator="(Ctrl + O)",
                command=self._trigger_ove_download,
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

    def split_section(self, index: int):
        """Split section at index"""
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
        """Deactivate cut mode (ESC key)"""
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

    def show_save_dialog(self, event=None):
        """Show advanced save dialog"""
        # Ignore if user is typing in an entry/text widget
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text, ctk.CTkEntry, ctk.CTkTextbox)):
            return


            
        # Default dir is last loaded file or Documents
        initial_dir = self.config.get_last_loaded_dir()
        
        # Try to get directory from first document in viewer (if available)
        if hasattr(self, 'viewer') and self.viewer.documents:
            first_doc = self.viewer.documents[0]
            if hasattr(first_doc, 'filepath') and first_doc.filepath:
                 initial_dir = str(first_doc.filepath.parent)
        
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
                
            # Filter valid boxes - include boxes with pages OR valid file_path
            # Boxes from collapsed sections have pages but may not have file_path
            valid_boxes = [b for b in boxes_to_save if 
                          (hasattr(b, 'pages') and b.pages) or 
                          (b.file_path and Path(b.file_path).exists())]
            
            if not valid_boxes:
                messagebox.showinfo("Info", "No hay cajas con archivos válidos para guardar")
                return
                
            # Wrap boxes to look like Sections for the dialog
            wrapped_sections = []
            for box in valid_boxes:
                # Approximate page count if not available
                p_count = len(box.pages) if hasattr(box, 'pages') and box.pages else 0
                
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
                
            SaveDialog(self.root, wrapped_sections, initial_dir, self._save_boxes)
            return
            
        # --- VIEWER MODE HANDLING ---
        # Only show saveable sections (exclude 'Borrados')
        saveable_sections = self.section_manager.get_saveable_sections()
        if not saveable_sections:
            messagebox.showinfo("Info", "No hay secciones para guardar")
            return
             
        SaveDialog(self.root, saveable_sections, initial_dir, self._save_sections)

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
                if not filename.lower().endswith(".pdf"):
                    filename += ".pdf"
                
                stem = filename[:-4]
                split_config = section.split_config
                
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
                        
                    stem = re.sub(r'/\d+[pPbBmMkK]$', '', stem)
                    
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
                
                if split_config:
                    val, type_ = split_config
                    
                    if type_ == 'p':
                        chunk_size = int(val)
                        for i in range(0, len(pages), chunk_size):
                            chunk = pages[i:i + chunk_size]
                            start_rel = i + 1
                            end_rel = i + len(chunk)
                            part_filename = f"{base_output_name.name}_p{start_rel}-p{end_rel}.pdf"
                            part_path = target_path / part_filename
                            plan_output(part_path, chunk)
                            
                    elif type_ == 'b':
                        limit_bytes = int(val)
                        current_chunk = []
                        current_start_idx = 0
                        
                        i = 0
                        while i < len(pages):
                            current_chunk.append(pages[i])
                            
                            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                                tmp_path = tmp.name
                            
                            try:
                                self.viewer.save_subset(tmp_path, current_chunk, silent=True)
                                size = os.path.getsize(tmp_path)
                                
                                if size > limit_bytes and len(current_chunk) > 1:
                                    current_chunk.pop()
                                    i -= 1
                                    
                                    start_rel = current_start_idx + 1
                                    end_rel = start_rel + len(current_chunk) - 1
                                    part_filename = f"{base_output_name.name}_p{start_rel}-p{end_rel}.pdf"
                                    part_path = target_path / part_filename
                                    plan_output(part_path, current_chunk)
                                    
                                    current_chunk = []
                                    current_start_idx = i + 1
                                    
                                elif size > limit_bytes and len(current_chunk) == 1:
                                    start_rel = current_start_idx + 1
                                    end_rel = start_rel
                                    part_filename = f"{base_output_name.name}_p{start_rel}-p{end_rel}.pdf"
                                    part_path = target_path / part_filename
                                    plan_output(part_path, current_chunk)
                                    
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
                            start_rel = current_start_idx + 1
                            end_rel = start_rel + len(current_chunk) - 1
                            part_filename = f"{base_output_name.name}_p{start_rel}-p{end_rel}.pdf"
                            part_path = target_path / part_filename
                            plan_output(part_path, current_chunk)
                            
                else:
                    output_path = target_path / filename
                    plan_output(output_path, pages)

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
                        self.viewer.save_subset(str(temp_output), pages_subset)
                        
                        # Verify save success
                        if temp_output.exists() and temp_output.stat().st_size > 0:
                            if output_path.exists():
                                try:
                                    output_path.unlink()
                                except PermissionError:
                                    # Retry rename/replace trick for Windows
                                    pass
                            
                            # Atomic replace (or as atomic as Windows allows)
                            import shutil
                            shutil.move(str(temp_output), str(output_path))
                        else:
                            raise Exception("Temporary file creation failed")

                        saved_count += 1
                        log.info(f"✓ Guardado: {output_path.name}")
                        
                    except Exception as e:
                        if 'temp_output' in locals() and temp_output.exists():
                            try:
                                temp_output.unlink()
                            except: pass
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
                        self.viewer.save_subset(str(temp_combined), all_pages_combined)
                        
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
        target_path.mkdir(parents=True, exist_ok=True)
        
        self.update_status("Guardando archivos...")
        
        # Capturar combined_filename en variable local para el closure
        combined_name = combined_filename
        
        def save_worker():
            try:
                # 1. Individual saves
                saved_files = []
                for item in to_save:
                    box_wrapper = item["section"] # It's actually a wrapper around the Box
                    box = box_wrapper.original_box
                    
                    filename = item["filename"]
                    if not filename.lower().endswith(".pdf"):
                        filename += ".pdf"
                        
                    dest_path = target_path / filename
                    
                    try:
                        # Priority: Always use pages if available (like _save_sections does)
                        # This ensures we save only the section's pages, not the entire original file
                        # CHECK: Update for Box Mode compatibility. box.pages might contain fitz.Page objects
                        # if loaded directly (Box Mode) but not expanded. We only want to use pages if 
                        # they are indices (tuples) from the viewer.
                        if hasattr(box, 'pages') and box.pages and isinstance(box.pages[0], tuple):
                            # Create PDF from pages in memory
                            # pages are tuples: (doc_index, page_index)
                            new_doc = fitz.open()
                            for page in box.pages:
                                if isinstance(page, tuple) and len(page) == 2:
                                    doc_idx, page_idx = page
                                    doc = self.viewer.documents[doc_idx]
                                    src_doc = fitz.open(doc.filepath)
                                    new_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)
                                    src_doc.close()
                            if new_doc.page_count > 0:
                                # Safe Save
                                tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
                                new_doc.save(tmp_path)
                                if dest_path.exists():
                                    try: dest_path.unlink()
                                    except: pass
                                import shutil
                                shutil.move(str(tmp_path), str(dest_path))
                                saved_files.append(dest_path)
                            new_doc.close()
                        elif box.file_path and Path(box.file_path).exists():
                            # Fallback: Copy original file only if no pages available
                            # (e.g., boxes loaded directly without expanding)
                            # Safe Save
                            import shutil
                            tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
                            shutil.copy2(box.file_path, tmp_path)
                            if dest_path.exists():
                                try: dest_path.unlink()
                                except: pass
                            shutil.move(str(tmp_path), str(dest_path))
                            saved_files.append(dest_path)
                    except Exception as e:
                        log.error(f"Error saving box {box.name}: {e}")
                        print(f"Error saving {box.name}: {e}")
                        
                # 2. Combined file
                if combined_name:
                    comb_filename = combined_name
                    if not comb_filename.lower().endswith(".pdf"):
                        comb_filename += ".pdf"
                        
                    combined_path = target_path / comb_filename
                    try:
                        merged_doc = fitz.open()
                        for item in to_save:
                            box = item["section"].original_box
                            
                            # Priority: Always use pages if available
                            # CHECK: Same fix as above
                            if hasattr(box, 'pages') and box.pages and isinstance(box.pages[0], tuple):
                                # Insert from pages in memory
                                # pages are tuples: (doc_index, page_index)
                                for page in box.pages:
                                    if isinstance(page, tuple) and len(page) == 2:
                                        doc_idx, page_idx = page
                                        doc = self.viewer.documents[doc_idx]
                                        src_doc = fitz.open(doc.filepath)
                                        merged_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)
                                        src_doc.close()
                            elif box.file_path and Path(box.file_path).exists():
                                # Fallback: Insert from original file
                                with fitz.open(box.file_path) as src_doc:
                                    merged_doc.insert_pdf(src_doc)
                                
                        merged_doc.save(combined_path)
                        merged_doc.close()
                    except Exception as e:
                        log.error(f"Error creating combined file: {e}")
                        print(f"Error creating combined file: {e}")
                
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
            self.grid.set_item_count(self.viewer.get_page_count())
            self.grid.set_sections(self.section_manager.sections)
            self.grid.redraw()
            
            self.update_status(f"Movidas {len(selected)} páginas a posición {target_idx}")
        else:
            self.update_status("Error al mover páginas")

    def update_status(self, text: str):
        """Update status bar text"""
        self.status_label.configure(text=text)

    def update_title(self, filename: str = None):
        """Update window title with filename"""
        title = "Podofilo V2 - PDF Manager"
        if self.version_label:
            title = f"{title} ({self.version_label})"
            
        if filename:
            title = f"{title} - {filename}"
            
        self.root.title(title)

    def _snap_to_zoom_level(self, size: int) -> int:
        """Ajustar tamaño al nivel de zoom más cercano"""
        # Encontrar el nivel más cercano
        closest = min(self.zoom_levels, key=lambda x: abs(x - size))
        return closest
    
    def _get_zoom_percentage(self, size: int) -> int:
        """Convertir tamaño de thumbnail a porcentaje (base: 150px = 100%)"""
        return int((size / 150) * 100)
    
    def zoom_in(self, event=None):
        """Increase thumbnail size"""
        if self.grid.box_mode:
            return
        
        # Encontrar el siguiente nivel de zoom
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
        """Decrease thumbnail size"""
        if self.grid.box_mode:
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
        """Reset thumbnail size"""
        if self.grid.box_mode:
            return

        self.thumbnail_size = 150
        self.grid.set_thumbnail_size(150)
        self.config.set_thumbnail_size(150)
        self.update_status("Zoom: 100%")
    
    def on_mouse_wheel(self, event):
        """Handle mouse wheel events for zoom with CTRL"""
        # Check if CTRL is pressed
        if event.state & 0x4:  # 0x4 is the Control key mask
            if self.grid.box_mode:
                return "break"

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
    
    def delete_selected(self, event=None):
        """Delete selected pages/boxes (Supr)"""
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

        # If we already have pages, assume synced
        if self.viewer.get_page_count() > 0:
            return True

        # Need at least one box to sync
        if not self.grid.document_boxes:
            return False

        log.info("Syncing backend from Boxes (Lazy Initialization)...")
        from src.pdf.structure import Section
        
        # Clear current viewer state to ensure clean slate
        # We must load documents properly into PdfViewer so it can render pages
        self.viewer.close_all()
        self.section_manager.sections = []
        
        current_page_idx = 0
        
        for box in self.grid.document_boxes:
            # Skip if box has no file (e.g. still downloading OVE)
            path = getattr(box, 'file_path', None)
            if not path or not path.exists():
                log.warning(f"Skipping sync for box {box.name}: No file path")
                continue
                
            try:
                # Load PDF into viewer (populates documents and pages list)
                added_count = self.viewer.load_pdf(str(path))
                
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

            # Find the start page of this box in the viewer
            if index < len(self.section_manager.sections):
                section = self.section_manager.sections[index]
                self.open_page_editor_for_page(section.start_page)
            else:
                # Fallback
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
    
    def _on_editor_closed(self, page_index: int):
        """Callback when editor closes"""
        log.debug(f"Editor closed for page {page_index}")
        # Future: Here we could refresh the thumbnail if the page was modified
    
    def add_page_numbering(self, event=None):
        """Add page numbering to selected pages in the document (in memory)"""
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
        
        # Filter out pages in "Borrados" section
        pages_to_number = []
        for page_idx in selected_pages:
            section = self.section_manager.get_section_at(page_idx)
            log.debug(f"Page {page_idx}: section={section.title if section else 'None'}, is_special={section.is_special if section else 'N/A'}")
            if section and not section.is_special:
                pages_to_number.append(page_idx)
        
        log.info(f"Selected: {len(selected_pages)}, To number: {len(pages_to_number)}, Excluded: {len(selected_pages) - len(pages_to_number)}")
        
        if not pages_to_number:
            messagebox.showwarning(
                "Sin Páginas Válidas",
                "Las páginas seleccionadas están en la sección 'Borrados'.\n\n"
                "Solo se pueden numerar páginas de secciones normales."
            )
            return
        
        # Show confirmation dialog
        excluded_count = len(selected_pages) - len(pages_to_number)
        excluded_msg = f"\n\n(Se excluirán {excluded_count} página(s) de la sección 'Borrados')" if excluded_count > 0 else ""
        
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
        log.info(f"Adding page numbering to {len(pages_to_number)} selected pages (excluding Borrados)")
        
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
                fontsize = self.numbering_fontsize
                text_width = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
                insert_rect, text_rotation = self._get_numbering_draw_params(page, text_width)
                log.debug(
                    "Numbering page idx=%s (doc=%s page=%s) size=(%.1f x %.1f) rot=%s -> pos=(%.1f, %.1f) text='%s'",
                    page_logical_idx,
                    doc_idx,
                    page_num_in_doc,
                    page_width,
                    page_height,
                    page.rotation,
                    insert_rect.x0,
                    insert_rect.y0,
                    text,
                )
                
                # Insert text
                rc = page.insert_textbox(
                    insert_rect,
                    text,
                    fontname="helv",
                    fontsize=fontsize,
                    color=(0, 0, 0),
                    align=fitz.TEXT_ALIGN_CENTER,
                    rotate=text_rotation
                )
                
                if rc < 0:
                    log.warning(f"Text overflow on page {page_logical_idx}: rc={rc}, rect={insert_rect}, text='{text}'")
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
                pages_to_clean.append(page_idx)
        
        if not pages_to_clean:
            messagebox.showwarning(
                "Sin Páginas Válidas",
                "Las páginas seleccionadas están en la sección 'Borrados'.\n\n"
                "Solo se puede eliminar numeración de páginas de secciones normales."
            )
            return
        
        # Show confirmation dialog
        excluded_count = len(selected_pages) - len(pages_to_clean)
        excluded_msg = f"\n\n(Se excluirán {excluded_count} página(s) de la sección 'Borrados')" if excluded_count > 0 else ""
        
        result = messagebox.askyesno(
            "Eliminar Numeración",
            f"Se eliminará la numeración de {len(pages_to_clean)} página(s) seleccionada(s).{excluded_msg}\n\n"
            f"Esto borrará cualquier texto de numeración añadido previamente.\n\n"
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
        removing_dialog.update_idletasks()
        x = (removing_dialog.winfo_screenwidth() // 2) - 200
        y = (removing_dialog.winfo_screenheight() // 2) - 75
        removing_dialog.geometry(f"400x150+{x}+{y}")
        
        ctk.CTkLabel(
            removing_dialog, 
            text=f"Eliminando numeración de {len(pages_to_clean)} páginas...", 
            font=("Segoe UI", 11),
            wraplength=350
        ).pack(expand=True, pady=(30, 10))
        
        progress_bar = ctk.CTkProgressBar(removing_dialog, width=350, mode="indeterminate")
        progress_bar.pack(pady=(0, 30))
        progress_bar.start()
        
        removing_dialog.update()
        log.debug("'Eliminando numeración...' dialog displayed")
        
        # Remove numbering from pages
        self.update_status("Eliminando numeración...")
        log.info(f"Removing page numbering from {len(pages_to_clean)} selected pages")
        
        try:
            removed_count = 0
            
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
                search_height = fontsize * 3  # Area to search for numbering text
                
                if "bottom" in position:
                    search_rect = fitz.Rect(
                        0, rect.height - margin - search_height,
                        rect.width, rect.height
                    )
                elif "top" in position:
                    search_rect = fitz.Rect(
                        0, 0,
                        rect.width, margin + search_height
                    )
                else:  # middle
                    mid_y = rect.height / 2
                    search_rect = fitz.Rect(
                        0, mid_y - search_height,
                        rect.width, mid_y + search_height
                    )
                
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

    def _get_numbering_draw_params(self, page: fitz.Page, text_width: float):
        """Return rectangle (fitz.Rect) and rotation so the text appears horizontal visually."""
        # page.rect in PyMuPDF reflects the *visual* dimensions (swapped if rotated 90/270)
        rect = page.rect
        visual_width = rect.width
        visual_height = rect.height
        rotation = int(page.rotation) % 360
        
        margin = max(0, self.numbering_margin)
        fontsize = self.numbering_fontsize
        position = self.numbering_position or "bottom-center"
        
        rect_width = max(text_width + fontsize, fontsize * 4)
        # PyMuPDF insert_textbox needs height >= fontsize * 1.9 for text to fit
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
            # User requested to reduce space by half (margin / 2)
            center_y = visual_height - (margin / 2) - rect_height / 2
        else:
            center_y = visual_height / 2
        
        # Clamp centers so the rect stays within bounds
        half_w = rect_width / 2
        half_h = rect_height / 2
        center_x = min(max(center_x, half_w), max(half_w, visual_width - half_w))
        center_y = min(max(center_y, half_h), max(half_h, visual_height - half_h))
        
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
            
            fontsize = self.numbering_fontsize
            text_width = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
            insert_rect, text_rotation = self._get_numbering_draw_params(page, text_width)
            log.debug(
                "Numbering single page=%s size=(%.1f x %.1f) rot=%s -> pos=(%.1f, %.1f) text='%s'",
                page_index,
                page_width,
                page_height,
                page.rotation,
                insert_rect.x0,
                insert_rect.y0,
                text,
            )
            
            # Insert text
            page.insert_textbox(
                insert_rect,
                text,
                fontname="helv",
                fontsize=fontsize,
                color=(0, 0, 0),
                align=fitz.TEXT_ALIGN_CENTER,
                rotate=text_rotation
            )
            
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
        SettingsDialog(self.root, self.config, ove_enabled=bool(self.extensions))
    
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

        # Copiar Log button
        def copy_log():
             content = text_widget.get("1.0", "end-1c")
             self.root.clipboard_clear()
             self.root.clipboard_append(content)
             self.root.update()
             # No feedback dialog


        copy_btn = ctk.CTkButton(
            btn_frame,
            text="Copiar Log",
            command=copy_log,
            width=120
        )
        copy_btn.pack(side="left", padx=5)
        
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
            
            # Filter PDF files
            pdf_files = [f for f in files if os.path.isfile(f) and f.lower().endswith('.pdf')]
            
            if len(pdf_files) == 1:
                # Single file: load directly
                self.load_pdf(pdf_files[0])
            elif len(pdf_files) > 1:
                # Multiple files: use box mode
                self.load_multiple_pdfs(pdf_files)
            
            if len(pdf_files) > 0:
                self.update_status(f"Cargados {len(pdf_files)} archivos arrastrados")
                
        except Exception as e:
            log.error(f"Error handling drop: {e}")

    def open_pdf(self):
        """Open PDF file dialog"""
        filetypes = [("PDF files", "*.pdf"), ("All files", "*.*")]
        
        # Use last loaded directory as starting point
        initial_dir = self.config.get_last_loaded_dir()
        
        filenames = filedialog.askopenfilenames(
            parent=self.root,
            title="Seleccionar PDFs",
            filetypes=filetypes,
            initialdir=initial_dir
        )
        
        if filenames:
            if len(filenames) == 1:
                # Single file: load directly
                self.load_pdf(filenames[0])
            else:
                # Multiple files: use box mode
                self.load_multiple_pdfs(filenames)
    
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
                        self._collapsed_boxes_backup = []
                        for section in self.section_manager.get_saveable_sections():
                            self._collapsed_boxes_backup.append({
                                'name': section.title,
                                'file_path': None,
                                'page_count': section.page_count
                            })
                    
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
            self.btn_expand.pack(side="right", padx=5, after=self.btn_ove)
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

                    # 3. Load PDF using fitz
                    box.progress = 0.45
                    update_ui_safe(lambda: self.grid.update_box_state(box_index))
                    
                    import fitz
                    doc = fitz.open(actual_load_path)
                    
                    box.progress = 0.6
                    update_ui_safe(lambda: self.grid.update_box_state(box_index))
                    
                    # Store pages as fitz.Page objects
                    pages = [doc[i] for i in range(len(doc))]
                    
                    # Set internal state to LOADED (this generates the static thumbnail)
                    box.set_loaded(pages)
                    
                    # Update display - UI safe
                    update_ui_safe(lambda: self.grid.update_box_state(box_index))
                    
                    log.info(f"Loaded {box.name}: {len(pages)} pages")

                    # --- INTEGRACION ANALISIS V2 ---
                    try:
                        if len(doc) > 0:
                            page0 = doc[0]
                            text = page0.get_text()
                            rect = page0.rect
                            res = analisis.analizar_pagina(text, rect.width, rect.height)
                            
                            exp_encontrado = None
                            if res.expedientes:
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
                                update_ui_safe(lambda: self.grid.update_box_state(box_index))
                                
                    except Exception as e_ana:
                        log.error(f"Error in PDF Analysis for {box.name}: {e_ana}")
                    # -------------------------------
                
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
            # Incluimos path, nombre y estado
            path = str(box.file_path) if box.file_path else ""
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
            
        # Evitar precarga si hay cajas todavía en proceso de carga
        if any(box.state in (BoxState.QUEUED, BoxState.LOADING) for box in self.grid.document_boxes):
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
                
                if box.state != BoxState.LOADED or not box.file_path:
                    continue
                
                try:
                    # Cargar PDF (esto abre el fitz.Document)
                    added_pages = temp_viewer.load_pdf(str(box.file_path))
                    
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
        if self._warmed_up_state and self._warmed_up_state['hash'] == current_hash:
            log.info("Usando expansión precargada para transición instantánea.")
            self.add_undo_snapshot()
            
            # Transferir datos del viewer precargado al viewer principal
            warmed_viewer = self._warmed_up_state['viewer']
            self.viewer.close_all() # Cerrar documentos actuales si los hubiera
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
            "completed": False
        }
        
        # Check if we're re-expanding from collapsed boxes (pages already in memory)
        is_re_expansion = hasattr(self, '_viewer_pages_backup') and self._viewer_pages_backup
        
        def expand_task(progress_dialog):
            """Tarea de expansión que se ejecuta en hilo separado"""
            try:
                import time
                # Clear current viewer state
                self.viewer.pages = []
                self.section_manager.sections = []
                
                current_page = 0
                total_boxes = len(valid_boxes)
                last_update_time = 0
                
                for idx, box in enumerate(valid_boxes):
                    if progress_dialog.is_cancelled:
                        log.info("Expansión cancelada por el usuario")
                        break
                    
                    # Actualizar progreso (limitado a ~10 FPS para evitar overhead en UI)
                    current_time = time.time()
                    if current_time - last_update_time > 0.1 or idx == 0 or idx == total_boxes - 1:
                        progress_dialog.update_progress(
                            (idx / total_boxes) * 0.7,
                            f"Cargando: {box.name}"
                        )
                        last_update_time = current_time
                    
                    # Check if this is a merged box with file paths (need to load from files)
                    # This check comes FIRST because merged boxes may also have file_path
                    if box.metadata.get('merged_file_paths'):
                        # Merged box from initial load - need to load each file
                        merged_paths = box.metadata['merged_file_paths']
                        log.info(f"Expanding merged box '{box.name}' from {len(merged_paths)} files")
                        added_pages = 0
                        for file_path in merged_paths:
                            try:
                                pages_loaded = self.viewer.load_pdf(file_path)
                                added_pages += pages_loaded
                                log.info(f"  Loaded {pages_loaded} pages from {file_path}")
                            except Exception as e:
                                log.error(f"Error loading merged file {file_path}: {e}")
                        split_config = None
                    
                    # Check if this is a collapsed box (pages are tuples compatible with viewer)
                    elif box.metadata.get('section_id'):
                        # Re-expanding from collapsed state - pages are stored in box.pages as tuples
                        added_pages = len(box.pages)
                        self.viewer.pages.extend(box.pages)
                        log.info(f"Expanding collapsed box '{box.name}' with {added_pages} pages from memory")
                        
                        # Restore split config if present
                        split_config = box.metadata.get('split_config')
                    
                    else:
                        # Normal expansion from file
                        if not box.file_path or not box.file_path.exists():
                            log.warning(f"Box '{box.name}' has no file path, skipping")
                            continue
                        
                        # Add pages to viewer
                        log.info(f"Expanding box '{box.name}' from single file: {box.file_path}")
                        added_pages = self.viewer.load_pdf(str(box.file_path))
                        split_config = None
                    
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

                    # CRITICAL FIX: Close the underlying fitz document to release file lock
                    # If this was a file-based box (pages loaded from fitz.open), we must close it
                    # now that we have extracted what we need.
                    if box.pages and len(box.pages) > 0:
                        try:
                            first_page = box.pages[0]
                            # Check if it's a fitz.Page (has .parent)
                            if hasattr(first_page, 'parent') and first_page.parent:
                                # We can safely close the doc because standard viewer doesn't use these page objects
                                # The viewer re-loaded the PDF safely via PdfDocument above.
                                first_page.parent.close()
                                log.debug(f"Closed Box Mode document for {box.name}")
                        except Exception as e:
                            log.warning(f"Failed to close Box Mode doc for {box.name}: {e}")
                
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
            self.btn_collapse.pack(side="right", padx=5, after=self.btn_ove)
            
            # Clear selections
            self.grid.selected_indices.clear()
            if hasattr(self.viewer, 'selected_pages'):
                self.viewer.selected_pages.clear()
            
            # Update grid
            total_pages = self.viewer.get_page_count()
            all_sizes = self.viewer.get_all_page_sizes()
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
        
        if self.grid.box_mode:
            return  # Already in box mode
        
        if not self._can_collapse_to_boxes:
            return  # Nothing to collapse
        
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
        
        # Rebuild boxes text
        new_boxes = self._rebuild_boxes_from_sections(sections)
        
        # Store current viewer state for re-expansion
        self._viewer_pages_backup = self.viewer.pages.copy()
        self._viewer_docs_backup = self.viewer.documents.copy()
        
        # Switch to box mode
        self.grid.set_box_mode(new_boxes)
        
        # Hide collapse button, show expand button
        self.btn_collapse.pack_forget()
        self.btn_expand.pack(side="right", padx=5, after=self.btn_ove)
        
        # Update status
        self.update_status(f"Colapsadas {len(sections)} secciones a cajas - Reordena y pulsa INTRO para expandir")
        log.info(f"Collapsed to {len(new_boxes)} boxes")
    
    def _rebuild_boxes_from_sections(self, sections):
        """Helper to create Box objects from Sections"""
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
            
            # Get pages for this section from viewer
            section_pages = []
            for page_idx in range(section.start_page, section.end_page):
                if page_idx < len(self.viewer.pages):
                    section_pages.append(self.viewer.pages[page_idx])
            
            box.pages = section_pages
            
            # Generate thumbnail from first page
            # Use simple index check, avoid hasattr get_pixmap as viewer.pages contains tuples now
            if section.start_page < self.viewer.get_page_count():
                try:
                    # Try to use existing cache or render from viewer
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
        
        # Crear nueva caja fusionada
        # Nombre: combinar nombres o usar el primero + "(fusionado)"
        merged_name = boxes_to_merge[0].name
        if len(boxes_to_merge) == 2:
            merged_name = f"{boxes_to_merge[0].name} + {boxes_to_merge[1].name}"
        else:
            merged_name = f"{boxes_to_merge[0].name} (+{len(boxes_to_merge)-1})"
        
        # Determinar si las cajas vienen de carga inicial (tienen file_path) o de colapso (tienen 'section_id')
        # Las cajas de carga inicial necesitan re-cargar desde archivo
        # Las cajas colapsadas ya tienen tuplas (doc_idx, page_num) compatibles con viewer
        
        has_collapsed_sources = any(box.metadata.get('section_id') for box in boxes_to_merge)
        all_have_file_paths = all(hasattr(box, 'file_path') and box.file_path and not box.metadata.get('section_id') 
                                   for box in boxes_to_merge)
        
        # Combinar páginas de todas las cajas
        merged_pages = []
        merged_file_paths = []  # Solo para cajas que NO vienen de colapso
        
        for box in boxes_to_merge:
            merged_pages.extend(box.pages)
            # Solo guardar file_path si la caja NO viene de colapso (tiene pages como tuplas)
            if hasattr(box, 'file_path') and box.file_path and not box.metadata.get('section_id'):
                merged_file_paths.append(str(box.file_path))
        
        log.info(f"Merging {len(boxes_to_merge)} boxes: has_collapsed={has_collapsed_sources}, all_have_files={all_have_file_paths}, total_pages={len(merged_pages)}")
        
        # Crear la nueva caja fusionada
        merged_box = LocalDocumentBox(
            name=merged_name,
            file_path=boxes_to_merge[0].file_path,  # Usar el path del primero
            state=BoxState.LOADED,
            progress=1.0
        )
        merged_box.pages = merged_pages
        
        # Usar thumbnail del primer documento
        if boxes_to_merge[0].thumbnail:
            merged_box.thumbnail = boxes_to_merge[0].thumbnail
        
        # Copiar metadata relevante
        merged_box.metadata['merged_from'] = [box.name for box in boxes_to_merge]
        
        # IMPORTANTE: Si ALGUNA caja viene de colapso, debemos usar las páginas directamente
        # porque las páginas de colapso son tuplas del viewer que no se pueden re-cargar desde archivo
        if has_collapsed_sources:
            merged_box.metadata['section_id'] = 'merged'  # Usar páginas directamente al expandir
            log.info(f"Merged box marked as collapsed (will use {len(merged_pages)} pages from memory)")
        elif all_have_file_paths and merged_file_paths:
            # Solo si TODAS las cajas tienen file_path y NINGUNA viene de colapso
            merged_box.metadata['merged_file_paths'] = merged_file_paths
            log.info(f"Merged box will load from {len(merged_file_paths)} files: {merged_file_paths}")
        
        # Insertar la caja fusionada en la posición del primer seleccionado
        insert_pos = selected[0]
        
        # Eliminar las cajas originales (de mayor a menor índice para no afectar posiciones)
        for idx in reversed(selected):
            del self.grid.document_boxes[idx]
        
        # Insertar la nueva caja fusionada
        self.grid.document_boxes.insert(insert_pos, merged_box)
        
        # Actualizar tamaños y caches
        self.grid.box_sizes = [(150, 200) for _ in self.grid.document_boxes]
        self.grid.item_sizes = self.grid.box_sizes.copy()
        self.grid.item_count = len(self.grid.document_boxes)
        self.grid.box_images.clear()
        
        # CRÍTICO: Limpiar tracking de Smart Redraw (los índices cambiaron)
        self.grid._clear_all_drawn_items()
        
        # Actualizar selección a la nueva caja fusionada
        self.grid.selected_indices = {insert_pos}
        
        # Refrescar display
        self.grid._update_layout()
        self.grid.redraw()
        
        total_pages = len(merged_pages)
        self.update_status(f"Fusionadas {len(boxes_to_merge)} cajas en '{merged_name}' ({total_pages} páginas)")
        log.info(f"Merged {len(boxes_to_merge)} boxes into '{merged_name}' with {total_pages} pages")
    
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

    def run(self):
        """Start application loop"""
        self.root.mainloop()
