"""
Virtual Grid Component
Renders thumbnails on a single canvas with virtualization for high performance.
Uses variable-width layout like V1.
Optimized with async rendering for 200+ page documents.
"""
import logging
import tkinter as tk
import customtkinter as ctk
import os
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageFilter
from typing import List, Callable, Optional, Tuple, Dict, TYPE_CHECKING
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty

from src.ui.sidebar import SyncedSidebar
from src.ui.theme import get_theme

def get_canvas_bg() -> str:
    """Get canvas background color based on current appearance mode - uses macOS theme"""
    theme = get_theme()
    return theme.CANVAS_BG

def get_box_colors():
    """Get box colors based on current appearance mode - uses macOS theme"""
    theme = get_theme()
    return {
        "bg": theme.THUMB_BG,
        "bg_failed": theme.THUMB_FAILED_BG,
        "bg_marked": theme.THUMB_MARKED_BG,
        "outline": theme.THUMB_BORDER,
        "text": theme.TEXT_PRIMARY,
        "text_secondary": theme.TEXT_SECONDARY,
        "loading_text": theme.TEXT_TERTIARY,
        "bar_bg": theme.PROGRESS_BG,
        "selection_border": theme.THUMB_SELECTED_BORDER,
        "hover_bg": theme.THUMB_HOVER_BG,
        "accent": theme.ACCENT_PRIMARY,
    }

if TYPE_CHECKING:
    from src.pdf.structure import Section

log = logging.getLogger(__name__)

# ============================================================================
# DRAG FAN OVERLAY - Efecto abanico al arrastrar páginas (como V1)
# ============================================================================

# Constantes del efecto abanico (igual que V1)
THUMB_ROTATION = math.radians(10)  # 10 grados de rotación
MAX_FAN_THUMBS = 5  # Máximo de miniaturas a mostrar en el abanico
SHADOW_OFFSET = 4  # Offset de la sombra
SHADOW_COLOR = (0, 0, 0, 100)  # Color de la sombra (RGBA)
FAN_THUMB_SIZE = 125  # Tamaño de las miniaturas del abanico
FAN_SUPERSAMPLE = 4  # Factor de supersampling para mejor calidad (renderizar a 2x y reducir)


class DragFanOverlay:
    """
    Overlay que muestra un abanico de miniaturas durante el drag.
    Replica el efecto visual de la V1 de Podofilo.
    """
    
    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        self.active = False
        self.thumbnails: List[Image.Image] = []  # PIL Images de las páginas
        self.fan_image: Optional[ImageTk.PhotoImage] = None
        self.canvas_item_id = None
        self.mouse_x = 0
        self.mouse_y = 0
        self._image_ref = None  # Mantener referencia para evitar GC
        
    def start(self, thumbnails: List[Image.Image]):
        """
        Inicia el efecto de abanico con las miniaturas dadas.
        Si hay más de MAX_FAN_THUMBS, muestra las 3 primeras y las 2 últimas.
        """
        if not thumbnails:
            return
            
        # Limitar a MAX_FAN_THUMBS (3 primeras + 2 últimas si hay más)
        if len(thumbnails) > MAX_FAN_THUMBS:
            self.thumbnails = thumbnails[:3] + thumbnails[-2:]
        else:
            self.thumbnails = thumbnails.copy()
        
        self.active = True
        self._create_fan_image()
        
    def update_position(self, x: int, y: int):
        """Actualiza la posición del abanico siguiendo el ratón"""
        if not self.active:
            return
            
        self.mouse_x = x
        self.mouse_y = y
        self._draw()
        
    def stop(self):
        """Detiene el efecto de abanico"""
        self.active = False
        self.thumbnails = []
        if self.canvas_item_id:
            try:
                self.canvas.delete(self.canvas_item_id)
            except:
                pass
            self.canvas_item_id = None
        self.fan_image = None
        self._image_ref = None
        
    def _create_fan_image(self):
        """
        Crea la imagen del abanico con todas las miniaturas rotadas.
        Replica el algoritmo de V1: las hojas se apilan con rotación progresiva.
        Usa supersampling para eliminar aliasing (dientes de sierra).
        """
        if not self.thumbnails:
            return
        
        num_thumbs = len(self.thumbnails)
        ss = FAN_SUPERSAMPLE  # Factor de supersampling
        
        # Escalar las miniaturas al tamaño de supersampling para mejor calidad
        scaled_thumbs = []
        for thumb in self.thumbnails:
            # Escalar a 2x para supersampling
            new_size = (thumb.width * ss, thumb.height * ss)
            scaled = thumb.resize(new_size, Image.Resampling.LANCZOS)
            scaled_thumbs.append(scaled)
        
        # Obtener tamaños escalados
        max_w = max(img.width for img in scaled_thumbs)
        max_h = max(img.height for img in scaled_thumbs)
        
        # Extra espacio por rotación (como V1) - escalado
        extra_rotation = int(max_h * math.sin(THUMB_ROTATION))
        extra_top = int(max_w * math.sin(THUMB_ROTATION))
        
        # Spread total basado en el número de miniaturas - escalado
        # En V1 las hojas están muy apiladas, solo se ve un pequeño borde
        spread_per_thumb = 5 * ss  # Píxeles de separación entre centros (muy compacto)
        total_spread = spread_per_thumb * (num_thumbs - 1) if num_thumbs > 1 else 0
        
        # Tamaño total del canvas del abanico (a escala de supersampling)
        shadow_offset_ss = SHADOW_OFFSET * ss
        fan_width = int(max_w + extra_rotation * 2 + total_spread + shadow_offset_ss * 2)
        fan_height = int(max_h + extra_top * 2 + shadow_offset_ss * 2)
        
        # Crear imagen RGBA para el abanico (a escala de supersampling)
        fan_img = Image.new('RGBA', (fan_width, fan_height), (0, 0, 0, 0))
        
        # Centro del abanico
        center_y = fan_height // 2
        
        # Calcular rango X para posicionar las miniaturas (como V1)
        min_x = shadow_offset_ss + int(max_w * (math.sin(THUMB_ROTATION) + 1) / 2)
        max_x = fan_width - min_x - shadow_offset_ss
        
        # Dibujar cada miniatura en orden inverso (la última debajo, la primera encima)
        for idx in reversed(range(num_thumbs)):
            thumb = scaled_thumbs[idx]
            pw, ph = thumb.size
            
            # Factor de posición: idx/(len-0.99) como en V1
            if num_thumbs > 1:
                pos_factor = idx / (num_thumbs - 0.99)
            else:
                pos_factor = 0.5
            
            # Posición X del centro de esta miniatura
            draw_center_x = int(min_x + (max_x - min_x) * pos_factor)
            
            # Rotación: de -THUMB_ROTATION a +THUMB_ROTATION
            rotation_angle = -THUMB_ROTATION + (THUMB_ROTATION * 2 * pos_factor)
            rotation_degrees = math.degrees(rotation_angle)
            
            # Añadir borde blanco a la miniatura (simula el papel) - escalado
            border_size = 3 * ss
            bordered = Image.new('RGBA', (pw + border_size * 2, ph + border_size * 2), (255, 255, 255, 255))
            bordered.paste(thumb.convert('RGBA'), (border_size, border_size))
            
            # Rotar la miniatura con alta calidad
            rotated = bordered.rotate(
                -rotation_degrees,  # Negativo porque PIL rota en sentido contrario
                expand=True,
                resample=Image.Resampling.BICUBIC,
                fillcolor=(0, 0, 0, 0)
            )
            
            # Crear sombra suave con desenfoque
            shadow = Image.new('RGBA', rotated.size, (0, 0, 0, 0))
            if rotated.mode == 'RGBA':
                alpha = rotated.split()[3]
                # Sombra más oscura y suave
                shadow_layer = Image.new('RGBA', rotated.size, (0, 0, 0, 0))
                shadow_layer.paste((0, 0, 0, 120), mask=alpha)
                # Aplicar desenfoque a la sombra para suavizarla
                shadow = shadow_layer.filter(ImageFilter.GaussianBlur(radius=ss))
            
            # Posición de pegado (centrado en draw_center_x, center_y)
            paste_x = draw_center_x - rotated.width // 2
            paste_y = center_y - rotated.height // 2
            
            # Pegar sombra primero (con offset)
            try:
                fan_img.alpha_composite(shadow, (paste_x + shadow_offset_ss, paste_y + shadow_offset_ss))
            except:
                fan_img.paste(shadow, (paste_x + shadow_offset_ss, paste_y + shadow_offset_ss), shadow)
            
            # Pegar miniatura
            try:
                fan_img.alpha_composite(rotated, (paste_x, paste_y))
            except:
                fan_img.paste(rotated, (paste_x, paste_y), rotated)
        
        # Reducir al tamaño final (elimina aliasing mediante supersampling)
        final_width = fan_width // ss
        final_height = fan_height // ss
        fan_img = fan_img.resize((final_width, final_height), Image.Resampling.LANCZOS)
        
        # Convertir a PhotoImage
        self._image_ref = ImageTk.PhotoImage(fan_img)
        self.fan_image = self._image_ref
        
    def _draw(self):
        """Dibuja el abanico en la posición actual del ratón"""
        if not self.active or not self.fan_image:
            return
            
        # Eliminar item anterior si existe
        if self.canvas_item_id:
            try:
                self.canvas.delete(self.canvas_item_id)
            except:
                pass
        
        # Convertir coordenadas de ventana a canvas
        canvas_x = self.canvas.canvasx(self.mouse_x)
        canvas_y = self.canvas.canvasy(self.mouse_y)
        
        # Offset para que el abanico esté cerca del cursor
        offset_x = 30
        offset_y = 20
        
        self.canvas_item_id = self.canvas.create_image(
            canvas_x + offset_x,
            canvas_y + offset_y,
            image=self.fan_image,
            anchor="center"
        )
        
        # Asegurar que el abanico esté encima de todo
        self.canvas.tag_raise(self.canvas_item_id)

class VirtualLayout:
    """Helper to calculate grid positions with variable widths"""
    def __init__(self):
        self.width = 1000
        self.total_height = 0
        self.positions: List[Tuple[int, int, int, int]] = [] # (x, y, width, height) for each item
        self.row_heights: Dict[int, int] = {} # y_pos -> height
        self.sepsize = 3  # Separation between items (V1 uses SEPSIZE = 3)
        self.continuous_mode = False
        self.section_header_coords: Dict[int, Tuple[int, int, int]] = {} # section_idx -> (x, y, max_width)

    def update(self, item_sizes: List[Tuple[int, int]], available_width: int, sections: List['Section'] = None):
        """
        Recalculate all positions using flow layout
        item_sizes: List of (width, height) for each item
        sections: List of Section objects defining logical groups
        """
        self.width = max(1, available_width)
        self.positions = []
        self.row_heights = {}
        self.section_bounds = {}
        self.section_header_coords = {}
        
        if not item_sizes:
            self.total_height = 0
            return
        
        # Flow layout: pack items left-to-right, wrap to next row when needed
        x = 0
        y = 0
        row_height = 0
        
        # Map start_page -> section_index
        section_starts = {s.start_page: i for i, s in enumerate(sections)} if sections else {}
        
        # Track active section
        current_section_start_y = 0
        active_section_idx = 0
        
        # Handle case where first section starts at 0
        if sections and 0 in section_starts:
            active_section_idx = section_starts[0]
            # First section starts at 0,0
            self.section_header_coords[active_section_idx] = (0, 0, 0) # Width calculated later

        if sections and not self.continuous_mode:
             # Ensure first section is tracked if not starting at 0 (unlikely but safe)
             if sections and active_section_idx not in self.section_header_coords:
                 self.section_header_coords[active_section_idx] = (0, 0, 0)

        
        for i, (w, h) in enumerate(item_sizes):
            # Check if this page starts a new section
            if i in section_starts and i > 0:
                 new_section_idx = section_starts[i]
                 
                 # Only trigger switch if we are actually changing sections (avoid re-triggering same)
                 if new_section_idx != active_section_idx:
                    # In normal mode, force new row for new section
                    # In continuous mode, ONLY force new row if NOT continuous
                    if not self.continuous_mode and (row_height > 0 or x > 0):
                        if row_height > 0:
                            self.row_heights[y] = row_height
                            y += row_height
                        elif x > 0:
                            y += row_height
                        x = 0
                        row_height = 0

                    # Record bounds for the sections that just ended
                    self.section_bounds[active_section_idx] = (current_section_start_y, y)
                    
                    # Handle skipped sections
                    for skipped_idx in range(active_section_idx + 1, new_section_idx):
                        self.section_bounds[skipped_idx] = (y, y)
                    
                    
                    current_section_start_y = y
                    active_section_idx = new_section_idx


            # Separation is constant (3px), not scaled with item size
            # Just add sepsize for spacing, not 2*sepsize
            item_w = w + self.sepsize
            item_h = h + self.sepsize
            
            # Check if item fits in current row
            if x > 0 and x + item_w > self.width:
                # Move to next row
                self.row_heights[y] = row_height
                y += row_height
                x = 0
                row_height = 0
            
            # Place item (no offset needed, separation is in item_w/item_h)
            self.positions.append((x, y, w, h))
            
            # Record header coords if this item started a new section
            # Check if this index was a start of a section
            if i in section_starts:
                # But wait, section_starts might have section index. 
                # section_starts = {start_page: section_idx}
                sec_idx = section_starts[i]
                self.section_header_coords[sec_idx] = (x, y, 0)
            
            x += item_w
            row_height = max(row_height, item_h)
        
        # Record last row height
        if row_height > 0:
            self.row_heights[y] = row_height
            y += row_height
        
        self.total_height = y
        
        # Record last section bounds
        if sections:
             self.section_bounds[active_section_idx] = (current_section_start_y, y)
             
             # If there were trailing empty sections (e.g. Borrados at end)
             for skipped_idx in range(active_section_idx + 1, len(sections)):
                 self.section_bounds[skipped_idx] = (y, y)
                 
        # Calculate max widths for section headers in continuous mode
        if sections and self.continuous_mode:
            for sec_idx, (sx, sy, _) in self.section_header_coords.items():
                section = sections[sec_idx]
                end_page = section.start_page + section.page_count
                
                # Find last item of this section THAT IS ON THE SAME ROW as the header
                # We iterate from start of section until we find a y change or end of section
                
                max_w = 0
                start_item_idx = section.start_page
                
                # Default to available width if something goes wrong
                line_max_w = self.width - sx
                
                if start_item_idx < len(self.positions):
                     # Scan items in this section to find the last one on this line
                     current_max_x = sx
                     for p_idx in range(start_item_idx, min(end_page, len(self.positions))):
                         px, py, pw, ph = self.positions[p_idx]
                         if py != sy:
                             break # Moved to next line
                         current_max_x = px + pw
                     
                     line_max_w = current_max_x - sx
                
                self.section_header_coords[sec_idx] = (sx, sy, line_max_w)


    def get_item_at(self, x: int, y: int) -> int:
        """Return index of item at coordinates, or -1"""
        if not self.positions:
            return -1
            
        # Linear search (could optimize with spatial indexing if needed)
        for i, (px, py, pw, ph) in enumerate(self.positions):
            if px <= x <= px + pw and py <= y <= py + ph:
                return i
                
        return -1

    def get_visible_range(self, scroll_y: int, view_height: int) -> Tuple[int, int]:
        """Get range of item indices visible in view"""
        if not self.positions:
            return 0, 0
        
        visible_top = scroll_y
        visible_bottom = scroll_y + view_height
        
        start_idx = None
        end_idx = None
        
        for i, (x, y, w, h) in enumerate(self.positions):
            item_bottom = y + h
            
            # Check if item is visible
            if item_bottom >= visible_top and y <= visible_bottom:
                if start_idx is None:
                    start_idx = i
                end_idx = i + 1
        
        return start_idx or 0, end_idx or 0

class VirtualGrid(ctk.CTkFrame):
    """
    Virtualized Grid for displaying thumbnails.
    Uses variable-width layout like V1.
    """
    def __init__(self, parent, on_double_click: Optional[Callable] = None, ove_enabled: bool = True, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.parent = parent
        self.ove_enabled = ove_enabled
        self.on_double_click = on_double_click
        
        # Layout helper
        self.layout = VirtualLayout()
        
        # State
        self.item_count = 0
        self.thumbnail_size = 150  # Target height
        self.item_sizes: List[Tuple[int, int]] = []  # Actual (width, height) for each item
        self.original_item_sizes: List[Tuple[int, int]] = []  # Original sizes at base thumbnail_size
        self.aspect_ratios: List[float] = []  # Width/Height ratio for each item
        self.base_thumbnail_size = 150  # Base size for original_item_sizes
        self.sections: List['Section'] = []
        # Caché multi-nivel: {thumbnail_size: {page_index: ImageTk.PhotoImage}}
        # Permite zoom instantáneo al volver a niveles anteriores
        self.images_cache: Dict[int, Dict[int, ImageTk.PhotoImage]] = {}
        self.max_zoom_levels_cached = 7  # Cachear TODOS los niveles de zoom (75-450px)
        self.selected_indices: set[int] = set()
        self.marked_indices: set[int] = set()  # Pages marked as blank
        self.bracket_start: Optional[int] = None
        self.hover_index: int = -1
        self.hover_side: Optional[str] = None
        self.hover_gap: Optional[int] = None  # For cut mode: index to split BEFORE
        self.hover_item_index: int = -1  # For hover effect on thumbnails
        self.drop_indicator_index: int = -1  # Where to show drop indicator
        self.cut_mode: bool = False # Toggle for cut mode
        self.continuous_mode: bool = False # Toggle for continuous view mode
        self.scissors_image: Optional[ImageTk.PhotoImage] = None
        
        self._header_hit_zones = {} # (x1, y1, x2, y2) -> section object
        self._header_items = {} # item_id -> section object (for robust hit testing)
        
        
        
        # Callbacks
        self.on_header_rename_request: Optional[Callable[[object], None]] = None
        self.on_header_right_click: Optional[Callable[[object, object], None]] = None # (section, event)
        
        # Document Box State (Staging Area)
        self.document_boxes: List = []  # List of DocumentBox instances
        self.box_mode: bool = False  # True when displaying boxes, False when displaying pages
        self.box_sizes: List[Tuple[int, int]] = []  # Sizes for boxes
        self.box_images: Dict[int, ImageTk.PhotoImage] = {}  # Cached box images
        
        self._load_resources()
        
        # Drag State
        self.drag_active = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drop_target_section = None # Initialize explicitly
        self.pending_click_index: Optional[int] = None
        self.pending_click_event = None
        
        # Callbacks
        self.on_request_image: Optional[Callable[[int, int], Image.Image]] = None
        self.on_selection_change: Optional[Callable[[], None]] = None
        self.on_right_click: Optional[Callable[[int, object], None]] = None
        self.on_drag_start: Optional[Callable[[int, object], None]] = None
        self.on_drag_motion: Optional[Callable[[int, object], None]] = None
        self.on_drag_end: Optional[Callable[[int, object], None]] = None
        self.on_split_request: Optional[Callable[[int], None]] = None
        
        # Async rendering system
        self._render_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ThumbnailRender")
        self._pending_renders: Dict[int, bool] = {}  # index -> True if pending
        self._render_queue = Queue()
        self._shutdown = False
        self._placeholder_image: Optional[ImageTk.PhotoImage] = None
        self._create_placeholder()
        
        # Smart Redraw: tracking de objetos dibujados para reutilización
        self._drawn_items: Dict[int, Dict[str, int]] = {}  # index -> {"base": canvas_id, "overlay": canvas_id, ...}
        self._last_visible_range: Tuple[int, int] = (0, 0)  # Para detectar cambios
        self._static_items: List[int] = []  # IDs de elementos estáticos (empty state, etc.)
        self._last_thumbnail_size: int = 150  # Para detectar cambios de zoom
        self._cut_indicator_ids: List[int] = []  # IDs de elementos del indicador de corte
        self._bracket_ids: List[int] = []  # IDs de brackets de selección
        
        # Cache de overlays por tamaño para evitar crear nuevos objetos PIL en cada frame
        self._selection_overlay_cache: Dict[Tuple[int, int], ImageTk.PhotoImage] = {}
        self._hover_overlay_cache: Dict[Tuple[int, int], ImageTk.PhotoImage] = {}
        
        # UI Setup
        self.grid_columnconfigure(1, weight=1) # Canvas is now col 1
        self.grid_rowconfigure(0, weight=1)
        
        # Sidebar
        self.sidebar = SyncedSidebar(self, width=40)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        
        # Canvas
        self.canvas = tk.Canvas(
            self,
            bg=get_canvas_bg(),
            highlightthickness=0,
            bd=0
        )
        self.canvas.grid(row=0, column=1, sticky="nsew")
        
        # Scrollbar
        self.scrollbar = ctk.CTkScrollbar(self, command=self._scroll_both)
        self.scrollbar.grid(row=0, column=2, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Drag Fan Overlay (efecto abanico como V1)
        self.drag_fan = DragFanOverlay(self.canvas)
        
        # Event bindings
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Control-Button-1>", self._on_ctrl_click)
        self.canvas.bind("<Shift-Button-1>", self._on_shift_click)
        self.canvas.bind("<Button-3>", self._on_right_click_event)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)


    @property
    def images(self) -> Dict[int, ImageTk.PhotoImage]:
        """Acceso compatible al caché de imágenes del nivel de zoom actual"""
        if self.thumbnail_size not in self.images_cache:
            self.images_cache[self.thumbnail_size] = {}
        return self.images_cache[self.thumbnail_size]
    
    def _get_image(self, index: int) -> Optional[ImageTk.PhotoImage]:
        """Obtener imagen del caché multi-nivel para el tamaño actual"""
        return self.images_cache.get(self.thumbnail_size, {}).get(index)
    
    def _set_image(self, index: int, image: ImageTk.PhotoImage):
        """Guardar imagen en el caché multi-nivel para el tamaño actual"""
        if self.thumbnail_size not in self.images_cache:
            self.images_cache[self.thumbnail_size] = {}
        self.images_cache[self.thumbnail_size][index] = image
        
        # Limitar el número de niveles en caché (LRU simple)
        if len(self.images_cache) > self.max_zoom_levels_cached:
            # Eliminar el nivel de zoom más antiguo (el primero insertado)
            oldest_level = next(iter(self.images_cache))
            if oldest_level != self.thumbnail_size:  # No eliminar el actual
                del self.images_cache[oldest_level]

    def _load_resources(self):
        """Load resources like icons"""
        self.loading_placeholder = None
        
        try:
            # Resolve path to iconos.png in repo root
            current_dir = os.path.dirname(os.path.abspath(__file__))
            repo_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
            icon_path = os.path.join(repo_root, "resources", "iconos.png")
            
            if os.path.exists(icon_path):
                full_atlas = Image.open(icon_path)
                # Tijeras at 0, 256, 64x64
                scissors = full_atlas.crop((0, 256, 64, 320))
                scissors = scissors.resize((64, 64), Image.Resampling.LANCZOS)
                self.scissors_image = ImageTk.PhotoImage(scissors)
            else:
                print(f"DEBUG: Icon file not found at {icon_path}")
                log.warning(f"Icon file not found at {icon_path}")
            
            # Crear imagen placeholder para carga
            self._create_loading_placeholder()
                
        except Exception as e:
            print(f"DEBUG: Failed to load resources: {e}")
            log.error(f"Failed to load resources: {e}")
    
    def _create_loading_placeholder(self):
        """Crear imagen placeholder animada para mostrar durante la carga"""
        try:
            # Crear imagen de documento con icono de carga
            size = 80
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Dibujar icono de documento
            doc_color = (100, 100, 100, 200)
            # Cuerpo del documento
            draw.rectangle([10, 5, 60, 75], fill=doc_color, outline=(150, 150, 150, 255), width=2)
            # Esquina doblada
            draw.polygon([(45, 5), (60, 20), (45, 20)], fill=(80, 80, 80, 200))
            # Líneas de texto simuladas
            line_color = (70, 70, 70, 180)
            for i in range(4):
                y = 30 + i * 10
                draw.rectangle([18, y, 52, y + 4], fill=line_color)
            
            self.loading_placeholder = ImageTk.PhotoImage(img)
            
        except Exception as e:
            log.error(f"Error creating loading placeholder: {e}")

    def set_item_count(self, count: int, page_sizes: List[Tuple[int, int]] = None):
        """Set number of items and refresh - OPTIMIZED for large documents"""
        self.item_count = count
        self.item_sizes = []
        self.original_item_sizes = []
        self.aspect_ratios = []
        self.base_thumbnail_size = self.thumbnail_size
        self.images_cache.clear()  # Limpiar TODO el caché multi-nivel (nuevo documento)
        self._pending_renders.clear()
        
        # Limpiar tracking de Smart Redraw (nuevo documento = nuevos items)
        self._clear_all_drawn_items()
        
        if page_sizes and len(page_sizes) == count:
            # Use actual page sizes if provided
            for w, h in page_sizes:
                aspect = w / h if h > 0 else 0.707
                target_w = round(self.thumbnail_size * aspect)
                target_h = self.thumbnail_size
                self.item_sizes.append((target_w, target_h))
                self.original_item_sizes.append((target_w, target_h))
                self.aspect_ratios.append(aspect)
        else:
            # Use estimated sizes initially (A4 aspect ratio ~0.707)
            # Real sizes will be updated when pages are rendered
            default_aspect = 0.707  # A4 portrait
            for i in range(count):
                w = round(self.thumbnail_size * default_aspect)
                h = self.thumbnail_size
                self.item_sizes.append((w, h))
                self.original_item_sizes.append((w, h))
                self.aspect_ratios.append(default_aspect)
        
        self._update_layout()
        self.redraw()
        
        # Schedule async size calculation for visible pages first (validation)
        self.after(10, self._async_calculate_sizes)

    def set_thumbnail_size(self, size: int):
        """Update thumbnail size - OPTIMIZED for instant zoom like V1"""
        self.thumbnail_size = size
        
        # Calculate sizes using aspect ratios for maximum precision
        # This ensures consistent sizing regardless of zoom level
        self.item_sizes = []
        for aspect_ratio in self.aspect_ratios:
            # Height is the target size, width is calculated from aspect ratio
            h = size
            w = round(h * aspect_ratio)
            self.item_sizes.append((w, h))
        
        # NO limpiamos el caché multi-nivel de imágenes - ¡Ese es el punto!
        # Las imágenes de otros niveles de zoom se mantienen para volver rápido
        # self.images.clear()  # <-- COMENTADO para zoom instantáneo
        
        # Clear pending renders if initialized (puede no existir durante __init__)
        if hasattr(self, '_pending_renders'):
            self._pending_renders.clear()
        
        # Limpiar caches de overlays (tamaños cambiaron) - solo si existen
        if hasattr(self, '_selection_overlay_cache'):
            self._selection_overlay_cache.clear()
        if hasattr(self, '_hover_overlay_cache'):
            self._hover_overlay_cache.clear()
        
        # Marcar que el tamaño cambió para forzar redibujado completo
        self._last_thumbnail_size = size
        
        # Limpiar tracking de objetos dibujados (zoom requiere recrear todo) - solo si está inicializado
        if hasattr(self, 'canvas'):
            self._clear_all_drawn_items()
        
        # Recalculate layout with new sizes (keeps separation constant at 3px)
        if hasattr(self, 'layout'):
            self._update_layout()
        
        # Redraw - images will be loaded on demand during draw
        if hasattr(self, 'canvas'):
            self.redraw()
            # Iniciar precarga de niveles adyacentes en segundo plano (después de un delay)
            self.after(500, self._preload_adjacent_zoom_levels)
    
    def _preload_adjacent_zoom_levels(self):
        """
        Pre-carga inteligente de niveles de zoom adyacentes en segundo plano.
        Renderiza el nivel anterior y siguiente para zoom instantáneo futuro.
        Solo procesa páginas visibles + buffer para no sobrecargar.
        """
        if self.box_mode or not hasattr(self, 'on_request_image') or not self.on_request_image:
            return
        
        # Obtener zoom levels definidos desde main_window
        if not hasattr(self, '_zoom_levels_for_preload'):
            # Niveles estándar si no se pasan desde main_window
            self._zoom_levels_for_preload = [75, 100, 120, 150, 180, 225, 300, 375, 450]
        
        zoom_levels = self._zoom_levels_for_preload
        
        try:
            current_idx = zoom_levels.index(self.thumbnail_size)
        except ValueError:
            # Tamaño actual no está en los niveles predefinidos
            return
        
        # Determinar niveles a pre-cargar (anterior y siguiente)
        levels_to_preload = []
        if current_idx > 0:
            levels_to_preload.append(zoom_levels[current_idx - 1])  # Nivel anterior
        if current_idx < len(zoom_levels) - 1:
            levels_to_preload.append(zoom_levels[current_idx + 1])  # Nivel siguiente
        
        if not levels_to_preload:
            return
        
        # Obtener rango visible + buffer
        scroll_y = self.canvas.canvasy(0)
        view_height = self.canvas.winfo_height()
        start_idx, end_idx = self.layout.get_visible_range(scroll_y, view_height)
        
        # Ampliar buffer para precarga (más páginas que para renderizado normal)
        buffer = 30
        start_idx = max(0, start_idx - buffer)
        end_idx = min(self.item_count, end_idx + buffer)
        
        # Pre-cargar niveles adyacentes en background thread
        def preload_worker():
            for zoom_size in levels_to_preload:
                # Verificar si ya está en caché
                if zoom_size in self.images_cache and len(self.images_cache[zoom_size]) > 0:
                    continue  # Ya tiene algo cacheado
                
                # Renderizar solo páginas visibles para este nivel
                for page_idx in range(start_idx, end_idx):
                    if self._shutdown:
                        return
                    
                    # Verificar si ya está cacheada
                    if zoom_size in self.images_cache and page_idx in self.images_cache[zoom_size]:
                        continue
                    
                    try:
                        # Renderizar la imagen (usa el caché global de PDF)
                        pil_img = self.on_request_image(page_idx, zoom_size)
                        if pil_img:
                            # Guardar en caché multi-nivel de forma thread-safe
                            def save_to_cache():
                                if zoom_size not in self.images_cache:
                                    self.images_cache[zoom_size] = {}
                                self.images_cache[zoom_size][page_idx] = ImageTk.PhotoImage(pil_img)
                            
                            # Ejecutar en main thread (Tkinter no es thread-safe)
                            self.after(0, save_to_cache)
                            
                            # Small delay para no saturar
                            import time
                            time.sleep(0.01)  # 10ms entre imágenes
                    except Exception as e:
                        log.debug(f"Error preloading page {page_idx} at zoom {zoom_size}: {e}")
                        continue
        
        # Ejecutar en background con baja prioridad
        import threading
        preload_thread = threading.Thread(target=preload_worker, daemon=True, name="ZoomPreload")
        preload_thread.start()
    
    
    def _create_placeholder(self):
        """Create placeholder image for pages that are still loading"""
        try:
            # Create a simple gray placeholder
            w = round(150 * 0.707)  # A4 aspect
            h = 150
            img = Image.new('RGB', (w, h), (64, 64, 64))
            draw = ImageDraw.Draw(img)
            # Add loading indicator
            draw.rectangle([10, h//2-2, w-10, h//2+2], fill=(80, 80, 80))
            self._placeholder_image = ImageTk.PhotoImage(img)
        except Exception as e:
            log.error(f"Error creating placeholder: {e}")
    
    def _async_calculate_sizes(self):
        """Calculate actual page sizes asynchronously for visible pages first"""
        if self._shutdown or self.item_count == 0:
            return
        
        # Get visible range
        scroll_y = self.canvas.canvasy(0)
        view_height = self.canvas.winfo_height()
        start_idx, end_idx = self.layout.get_visible_range(scroll_y, view_height)
        
        # Expand range with buffer
        buffer = 10
        start_idx = max(0, start_idx - buffer)
        end_idx = min(self.item_count, end_idx + buffer)
        
        # Calculate sizes for visible pages first
        needs_update = False
        for i in range(start_idx, end_idx):
            if i < len(self.aspect_ratios) and self.aspect_ratios[i] == 0.707:  # Still default
                if self.on_request_image:
                    try:
                        img = self.on_request_image(i, self.thumbnail_size)
                        if img:
                            actual_aspect = img.width / img.height if img.height > 0 else 0.707
                            self.aspect_ratios[i] = actual_aspect
                            w = round(self.thumbnail_size * actual_aspect)
                            h = self.thumbnail_size
                            self.item_sizes[i] = (w, h)
                            self.original_item_sizes[i] = (w, h)
                            needs_update = True
                    except Exception as e:
                        log.debug(f"Error getting size for page {i}: {e}")
        
        if needs_update:
            self._update_layout()
            self.redraw()
    
    def _render_page_async(self, index: int, size: int):
        """Submit page rendering to background thread"""
        if index in self._pending_renders or index in self.images:
            return
        
        self._pending_renders[index] = True
        
        def render_task():
            try:
                if self.on_request_image:
                    pil_img = self.on_request_image(index, size)
                    if pil_img:
                        # Schedule UI update on main thread
                        self.after(0, lambda: self._on_render_complete(index, pil_img))
            except Exception as e:
                log.debug(f"Async render error for page {index}: {e}")
            finally:
                self._pending_renders.pop(index, None)
        
        self._render_executor.submit(render_task)
    
    def _on_render_complete(self, index: int, pil_img: Image.Image):
        """Called when async render completes - updates UI on main thread"""
        if self._shutdown:
            return
        
        try:
            # Update aspect ratio if still default
            if index < len(self.aspect_ratios):
                actual_aspect = pil_img.width / pil_img.height if pil_img.height > 0 else 0.707
                if self.aspect_ratios[index] == 0.707:  # Still default
                    self.aspect_ratios[index] = actual_aspect
                    w = round(self.thumbnail_size * actual_aspect)
                    h = self.thumbnail_size
                    self.item_sizes[index] = (w, h)
                    self.original_item_sizes[index] = (w, h)
            
            # Store the image in multi-level cache
            self._set_image(index, ImageTk.PhotoImage(pil_img))
            
            # Check if this page is visible and redraw if so
            scroll_y = self.canvas.canvasy(0)
            view_height = self.canvas.winfo_height()
            start_idx, end_idx = self.layout.get_visible_range(scroll_y, view_height)
            
            if start_idx <= index < end_idx:
                self.redraw()
        except Exception as e:
            log.debug(f"Error completing render for page {index}: {e}")
    
    def shutdown(self):
        """Cleanup resources on shutdown"""
        self._shutdown = True
        self._render_executor.shutdown(wait=False)
    
    def _update_layout(self):
        """Recalculate positions"""
        self.layout.update(self.item_sizes, self.canvas.winfo_width(), self.sections)
        total_height = self.layout.total_height
        
        # Only allow scroll if content exceeds visible area
        # If content fits, align to top and disable scroll
        canvas_height = self.canvas.winfo_height()
        
        if canvas_height > 1:  # Canvas is initialized
            # Auto-hide scrollbar logic
            if total_height > canvas_height:
                if not self.scrollbar.winfo_ismapped():
                    self.scrollbar.grid(row=0, column=2, sticky="ns")
            else:
                if self.scrollbar.winfo_ismapped():
                    self.scrollbar.grid_remove()
                    
            scroll_height = max(total_height, canvas_height)
        else:
            scroll_height = total_height
            
        self.canvas.configure(scrollregion=(0, 0, self.layout.width, scroll_height))
        
        # Update sidebar
        if hasattr(self, 'sidebar'):
            self.sidebar.update_layout(self.sections, self.layout.section_bounds, scroll_height)

    def set_sections(self, sections: List['Section']):
        """Update sections and refresh layout"""
        self.sections = sections
        self._update_layout()
        self.redraw()
        
    def set_continuous_mode(self, enabled: bool):
        """Enable/Disable continuous view mode"""
        if self.continuous_mode == enabled:
            return
            
        self.continuous_mode = enabled
        self.layout.continuous_mode = enabled
        
        # Clear smart redraw cache because layout changes significantly
        self._clear_all_drawn_items()
        
        self._update_layout()
        self.redraw()

    
    # ========================================================================
    # DOCUMENT BOX METHODS (Staging Area)
    # ========================================================================
    
    def set_box_mode(self, boxes: List):
        """
        Switch to box mode (staging area).
        Displays document boxes instead of individual pages.
        """
        self.document_boxes = boxes
        self.box_mode = True
        self.item_count = len(boxes)
        
        # Reset Cut Mode if active
        self.cut_mode = False
        self.hover_gap = None
        if hasattr(self, 'canvas'):
            self.canvas.configure(cursor="")
        
        # Calculate box sizes (fixed size for all boxes)
        box_width = 150
        box_height = 200
        self.box_sizes = [(box_width, box_height) for _ in boxes]
        self.item_sizes = self.box_sizes.copy()
        self.aspect_ratios = [box_width / box_height for _ in boxes]
        
        # Clear caches
        self.images.clear()
        self.box_images.clear()
        self.selected_indices.clear()
        
        # Limpiar tracking de Smart Redraw (cambio de modo)
        self._clear_all_drawn_items()
        
        # Clear sections - in box mode we don't show section indicators
        self.sections = []
        
        # Update layout
        self._update_layout()
        self.redraw()
    
    def exit_box_mode(self):
        """
        Exit box mode and return to normal page display.
        Called after boxes are expanded.
        """
        # Cerrar documentos fitz de los boxes para liberar archivos
        for box in self.document_boxes:
            if hasattr(box, 'metadata') and box.metadata:
                doc = box.metadata.get('doc')
                if doc:
                    try:
                        doc.close()
                    except:
                        pass
                box.metadata.clear()
        
        self.box_mode = False
        self.document_boxes = []
        self.box_sizes = []
        self.box_images.clear()
        
        # Limpiar tracking de Smart Redraw (cambio de modo)
        self._clear_all_drawn_items()
    
    def get_box_at(self, index: int):
        """Get document box at index"""
        if 0 <= index < len(self.document_boxes):
            return self.document_boxes[index]
        return None
    
    def update_box_state(self, index: int):
        """Refresh display for a specific box (e.g., after progress update)"""
        if self.box_mode and 0 <= index < len(self.document_boxes):
            # Clear cached PhotoImage to force recreation from box.thumbnail
            if index in self.box_images:
                del self.box_images[index]
            
            # FULL Redraw of this specific item:
            # First, delete ALL existing canvas objects for this index (text, bars, images)
            self._delete_item_objects(index)
            # Then redraw cleanly
            self._draw_item_smart(index)
    
    def reorder_boxes(self, from_index: int, to_index: int):
        """Reorder boxes (drag and drop)"""
        if not self.box_mode:
            return
        
        if from_index == to_index:
            return
        
        # Move box
        box = self.document_boxes.pop(from_index)
        self.document_boxes.insert(to_index, box)
        
        # Clear box image cache as indices have changed
        self.box_images.clear()
        
        # CRÍTICO: Limpiar tracking de Smart Redraw (los índices cambiaron)
        self._clear_all_drawn_items()
        
        # Update layout and redraw
        self._update_layout()
        self.redraw()

    def reorder_selected_boxes(self, target_index: int) -> bool:
        """Reorder currently selected boxes preserving their relative order"""
        if not self.box_mode or not self.selected_indices:
            return False

        selected = sorted(self.selected_indices)
        if not selected:
            return False

        # Clamp target index within bounds (allow dropping after last item)
        target_index = max(0, min(target_index, len(self.document_boxes)))

        # Extract boxes to move and remaining boxes
        boxes_to_move = [self.document_boxes[i] for i in selected]
        remaining_boxes = [box for idx, box in enumerate(self.document_boxes) if idx not in self.selected_indices]

        if not boxes_to_move:
            return False

        # Adjust insertion index in the remaining list (ignore removed positions)
        removed_before_target = sum(1 for idx in selected if idx < target_index)
        insertion_index = target_index - removed_before_target
        insertion_index = max(0, min(insertion_index, len(remaining_boxes)))

        # Rebuild list
        self.document_boxes = (
            remaining_boxes[:insertion_index]
            + boxes_to_move
            + remaining_boxes[insertion_index:]
        )

        # Clear box image cache as indices have changed
        self.box_images.clear()
        
        # CRÍTICO: Limpiar tracking de Smart Redraw (los índices cambiaron)
        self._clear_all_drawn_items()

        # Update selection to new positions
        new_start = insertion_index
        self.selected_indices = set(range(new_start, new_start + len(boxes_to_move)))

        # Refresh layout/display
        self._update_layout()
        self.redraw()
        return True

    def _scroll_both(self, *args):
        """Sync scroll both canvases"""
        self.canvas.yview(*args)
        self.sidebar.yview(*args)

    def _on_resize(self, event):
        """Handle resize - Smart Redraw compatible"""
        # Guardar ancho anterior para detectar reflow
        old_width = getattr(self, '_last_canvas_width', 0)
        new_width = event.width
        
        # Si el ancho cambió significativamente, el layout hace reflow
        # y las posiciones cambian, así que limpiamos el tracking
        if abs(new_width - old_width) > 5:
            self._clear_all_drawn_items()
            self._last_canvas_width = new_width
        
        self._update_layout()
        self.redraw()

    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling - OPTIMIZED with debounce"""
        # If CTRL is pressed, don't scroll - let main_window handle zoom
        if event.state & 0x4:  # 0x4 is the Control key mask
            return
        
        units = int(-1*(event.delta/120))
        self.canvas.yview_scroll(units, "units")
        self.sidebar.yview_scroll(units, "units")
        
        # Debounce redraw during fast scrolling
        if hasattr(self, '_scroll_redraw_pending') and self._scroll_redraw_pending:
            return
        
        self._scroll_redraw_pending = True
        self.after(16, self._debounced_scroll_redraw)  # ~60fps
    
    def _debounced_scroll_redraw(self):
        """Debounced redraw after scroll"""
        self._scroll_redraw_pending = False
        self.redraw()
        self.sidebar.redraw()

    def find_item_above(self, index: int) -> int | None:
        """Find the item visually above the given index in the grid"""
        if index < 0 or index >= len(self.layout.positions):
            return None
        
        x, y, w, h = self.layout.positions[index]
        center_x = x + w / 2
        
        # Find items in the row above (lower y value)
        best_match = None
        best_distance = float('inf')
        
        for i, (ix, iy, iw, ih) in enumerate(self.layout.positions):
            # Must be above current item (lower y)
            if iy + ih <= y:  # Item ends before current starts
                item_center_x = ix + iw / 2
                # Calculate horizontal distance
                h_distance = abs(item_center_x - center_x)
                # Calculate vertical distance (prefer closer rows)
                v_distance = y - (iy + ih)
                
                # Prioritize items that are close horizontally and in the nearest row above
                # Use a weighted score: vertical distance matters more for row selection
                score = v_distance * 1000 + h_distance
                
                if score < best_distance:
                    best_distance = score
                    best_match = i
        
        return best_match
    
    def find_item_below(self, index: int) -> int | None:
        """Find the item visually below the given index in the grid"""
        if index < 0 or index >= len(self.layout.positions):
            return None
        
        x, y, w, h = self.layout.positions[index]
        center_x = x + w / 2
        
        # Find items in the row below (higher y value)
        best_match = None
        best_distance = float('inf')
        
        for i, (ix, iy, iw, ih) in enumerate(self.layout.positions):
            # Must be below current item (higher y)
            if iy >= y + h:  # Item starts after current ends
                item_center_x = ix + iw / 2
                # Calculate horizontal distance
                h_distance = abs(item_center_x - center_x)
                # Calculate vertical distance (prefer closer rows)
                v_distance = iy - (y + h)
                
                # Prioritize items that are close horizontally and in the nearest row below
                score = v_distance * 1000 + h_distance
                
                if score < best_distance:
                    best_distance = score
                    best_match = i
        
        return best_match

    def scroll_to_item(self, index: int):
        """Scroll to make the item at index visible"""
        if index < 0 or index >= len(self.layout.positions):
            return
        
        x, y, w, h = self.layout.positions[index]
        
        # Get current scroll position and view height
        scroll_y = self.canvas.canvasy(0)
        view_height = self.canvas.winfo_height()
        total_height = self.layout.total_height
        
        if total_height <= view_height:
            return  # No need to scroll if everything fits
        
        # Check if item is already visible
        if y >= scroll_y and y + h <= scroll_y + view_height:
            return  # Already visible
        
        # Calculate target scroll position (center the item if possible)
        target_y = y - (view_height - h) / 2
        target_y = max(0, min(target_y, total_height - view_height))
        
        # Convert to fraction for yview_moveto
        fraction = target_y / total_height
        self.canvas.yview_moveto(fraction)
        self.sidebar.yview_moveto(fraction)
        self.redraw()
        self.sidebar.redraw()

    def clear_image_cache(self):
        """Clear cached images to force regeneration"""
        self.images.clear()
        log.debug("Grid image cache cleared")
    
    def _clear_all_drawn_items(self):
        """Limpia todos los objetos dibujados del canvas y el tracking"""
        self.canvas.delete("all")
        self._drawn_items.clear()
        self._static_items.clear()
        self._last_visible_range = (0, 0)
    
    def _delete_item_objects(self, index: int):
        """Elimina todos los objetos de canvas asociados a un índice"""
        if index in self._drawn_items:
            item_data = self._drawn_items[index]
            
            # Eliminar lista de IDs de base (modo BOXES)
            if "_base_ids" in item_data:
                for obj_id in item_data["_base_ids"]:
                    try:
                        self.canvas.delete(obj_id)
                    except:
                        pass
            
            # Eliminar otros objetos individuales
            for key, obj_id in item_data.items():
                if key.startswith("_"):  # Skip metadata keys
                    continue
                try:
                    self.canvas.delete(obj_id)
                except:
                    pass
            del self._drawn_items[index]
    
    def redraw(self):
        """
        Smart Redraw - Renderiza items visibles reutilizando objetos existentes.
        Filosofía: "No destruyas lo que puedes mover"
        """
        self._drop_line_refs = []
        self._drop_line_refs = []
        self._overlay_refs = {}
        self._header_hit_zones = {}
        self._header_items = {}
        
        # Clear section headers (ghosting fix)
        self.canvas.delete("section_header")
        
        # Limpiar indicadores de corte anteriores
        for cut_id in self._cut_indicator_ids:
            try:
                self.canvas.delete(cut_id)
            except:
                pass
        self._cut_indicator_ids.clear()
        
        # Limpiar brackets de selección anteriores
        for bracket_id in self._bracket_ids:
            try:
                self.canvas.delete(bracket_id)
            except:
                pass
        self._bracket_ids.clear()
        
        scroll_y = self.canvas.canvasy(0)
        view_height = self.canvas.winfo_height()
        start_idx, end_idx = self.layout.get_visible_range(scroll_y, view_height)
        
        # Caso especial: sin items
        if self.item_count == 0:
            self._clear_all_drawn_items()
            self._draw_empty_state()
            return
        
        # Limpiar elementos estáticos (empty state) si había
        for static_id in self._static_items:
            try:
                self.canvas.delete(static_id)
            except:
                pass
        self._static_items.clear()
        
        # Calcular qué items están visibles ahora
        visible_set = set(range(start_idx, end_idx))
        drawn_set = set(self._drawn_items.keys())
        
        # 1. Eliminar items que salieron de la vista
        to_remove = drawn_set - visible_set
        for i in to_remove:
            self._delete_item_objects(i)
        
        # 2. Eliminar overlays de TODOS los items dibujados (se recrean cada frame)
        #    Los overlays son baratos y cambian frecuentemente (selección, hover)
        for i in list(self._drawn_items.keys()):
            item_data = self._drawn_items[i]
            # Eliminar solo overlays, mantener base y metadata (claves que empiezan con _)
            overlay_keys = [k for k in item_data.keys() if k != "base" and not k.startswith("_")]
            for key in overlay_keys:
                try:
                    self.canvas.delete(item_data[key])
                except:
                    pass
                del item_data[key]
        
        # 3. Dibujar/Actualizar items visibles
        for i in range(start_idx, end_idx):
            self._draw_item_smart(i)
        
        # 4. Dibujar elementos temporales (cut indicator, drop indicator)
        if self.cut_mode and self.hover_gap is not None:
            self._draw_cut_indicator()
            
        if self.drop_indicator_index != -1 or self.drop_target_section:
            self._draw_drop_indicator()
        
        # 5. Redibujar abanico si está activo
        if self.drag_fan.active:
            self.drag_fan._draw()
            
        # 6. Draw Section Headers in Continuous Mode
        if self.continuous_mode and self.sections and not self.box_mode:
            self._draw_section_headers(scroll_y, view_height)
        
        self._last_visible_range = (start_idx, end_idx)


    def _draw_empty_state(self):
        """Draw empty state with shortcuts hints (VS Code style)"""
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        if width < 100 or height < 100:
            return
            
        cx = width / 2
        cy = height / 2
        
        # Style
        text_color = "#505050"  # Subtle gray
        cmd_font = ("Segoe UI", 16)
        shortcut_font = ("Segoe UI", 14)
        
        # Content
        # Content
        shortcuts = [
            ("Abrir PDF", "Ctrl + A / Arrastrar"),
        ]
        
        if self.ove_enabled:
            shortcuts.extend([
                ("Descargar Expediente desde OVE", "Ctrl + O"),
            ])
            
        shortcuts.append(("Guardar PDF", "Mayúsculas + S"))
        
        if self.ove_enabled:
            shortcuts.append(("Subir Expediente a OVE", "Ctrl + S"))
            
        shortcuts.extend([
            ("Seleccionar Todo/Nada", "Espacio"),
            ("Expandir / Colapsar", "Intro / Retroceso"),
            ("Editar Páginas Seleccionadas", "Tecla E"),
            ("Fusionar CAJAS (Modo BOX)", "Tecla F"),
            ("Añadir Numeración", "Tecla T"),
            ("Eliminar Numeración", "Mayúsculas + T"),
            ("Deshacer / Rehacer", "Ctrl + Z / Ctrl + Y"),
        ])
        
        # Calculate total height to center the block
        line_height = 35
        total_content_height = len(shortcuts) * line_height
        
        start_y = cy - (total_content_height / 2)
        
        for i, (cmd, key) in enumerate(shortcuts):
            y = start_y + (i * line_height)
            
            # Align Command to the right of center-gap
            self.canvas.create_text(
                cx - 20, y,
                text=cmd,
                font=cmd_font,
                fill=text_color,
                anchor="e"
            )
            
            # Align Shortcut to the left of center-gap
            self.canvas.create_text(
                cx + 20, y,
                text=key,
                font=shortcut_font,
                fill=text_color,
                anchor="w"
            )

    def _draw_section_headers(self, scroll_y, view_height):
        """Draw section headers for visible sections in continuous mode"""
        header_font = ("Segoe UI", 10, "bold")
        
        for i, section in enumerate(self.sections):
            if i not in self.layout.section_header_coords:
                continue
                
            x, y, max_w = self.layout.section_header_coords[i]
            
            # Skip if section not visible
            # Approximate height of section header box is ~25px
            if y > scroll_y + view_height or y + 30 < scroll_y:
                continue
                
            name = section.title
            if not name:
                continue
            
            # Create header background and text
            # We want a small box at the top-left of the first thumbnail
            
            # 1. Measure text width
            char_width = 7 # approx for size 10 bold
            text_width = len(name) * char_width
            padding = 20 # Extra breathing room
            
            # 2. Constraint: cannot assume full self.width. Must use max_w (section visual width on this line)
            # Use max_w calculated in layout
            limit_width = max(50, max_w) # At least 50px
            
            # 3. Calculate desired total width
            desired_width = text_width + padding
            
            # 4. Truncate if needed
            if desired_width > limit_width:
                 # Calculate how many chars fit
                 # (chars * char_width) + padding = limit_width
                 # chars = (limit_width - padding) / char_width
                 chars_fit = int((limit_width - padding) / char_width)
                 if chars_fit < 3: chars_fit = 3
                 display_text = name[:chars_fit-2] + "..."
                 final_width = limit_width
            else:
                 display_text = name
                 final_width = desired_width
            
            # Draw header

            # Draw header
            # Gray background, dark text
            bg_color = "#E0E0E0" if ctk.get_appearance_mode() == "Light" else "#404040"
            text_color = "#202020" if ctk.get_appearance_mode() == "Light" else "#E0E0E0"
            
            # Draw rounded rect (using polygon or oval+rect)
            # Simple rectangle for now
            h = 24 # Slightly taller
            
            # Background
            # Position: Aligned with top of thumbnail (y)
            rect_id = self.canvas.create_rectangle(
                x, y, 
                x + final_width, y + h,
                fill=bg_color,
                outline="",
                tags="section_header"
            )
            
            # Store hit info
            self._header_hit_zones[(x, y, x + final_width, y + h)] = section
            self._header_items[rect_id] = section

            # Text
            text_id = self.canvas.create_text(
                x + 5, y + h/2,
                text=display_text,
                font=header_font,
                fill=text_color,
                anchor="w",
                tags="section_header"
            )
            self._header_items[text_id] = section
            
            self._header_items[text_id] = section
            
            # (Tag bindings removed in favor of manual check in _on_right_click for reliability)

    def _handle_header_click(self, section):
        if self.on_header_rename_request:
            self.on_header_rename_request(section)
        elif hasattr(self.parent, 'rename_section'):
            self.parent.rename_section(section)
        return "break"


    def _draw_cut_indicator(self):
        """Draw scissors and line at hover_gap"""
        if self.hover_gap is None:
            return
            
        # Determine position between hover_gap-1 and hover_gap
        idx_left = self.hover_gap - 1
        idx_right = self.hover_gap
        
        cx, cy = 0, 0
        line_coords = None # (x1, y1, x2, y2)
        
        # Get coords
        if idx_left < 0:
             # Gap at start (before first item)
             if len(self.layout.positions) > 0:
                 xr, yr, wr, hr = self.layout.positions[0]
                 cx = xr
                 cy = yr + hr / 2
                 line_coords = (cx, yr, cx, yr+hr)
             else:
                 return

        elif idx_right >= len(self.layout.positions):
             # Gap at end (after last item)
             if len(self.layout.positions) > 0:
                 xl, yl, wl, hl = self.layout.positions[-1]
                 cx = xl + wl
                 cy = yl + hl / 2
                 line_coords = (cx, yl, cx, yl+hl)
             else:
                 return
        else:    
            xl, yl, wl, hl = self.layout.positions[idx_left]
            xr, yr, wr, hr = self.layout.positions[idx_right]
            
            # Check if they are on the same row (approximate check of y)
            same_row = abs(yl - yr) < 10
            
            if same_row:
                # Center between items
                cx = (xl + wl + xr) / 2
                cy = yl + hl / 2
                line_coords = (cx, yl, cx, yl+hl)
            else:
                # Different rows (wrap case)
                # Draw at start of new row (left of right item)
                cx = xr # Left edge of right item
                cy = yr + hr / 2
                line_coords = (cx, yr, cx, yr+hr)

        # Draw elements if coordinates found
        if line_coords:
            line_id = self.canvas.create_line(*line_coords, fill="#E04F5F", width=2, dash=(4, 2))
            self._cut_indicator_ids.append(line_id)
            
            if self.scissors_image:
                scissors_id = self.canvas.create_image(cx, cy, image=self.scissors_image, anchor="center")
                self._cut_indicator_ids.append(scissors_id)
            else:
                # Fallback shape if image missing
                r = 8
                oval_id = self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline="#E04F5F", width=2)
                line1_id = self.canvas.create_line(cx-4, cy-4, cx+4, cy+4, fill="#E04F5F", width=2)
                line2_id = self.canvas.create_line(cx-4, cy+4, cx+4, cy-4, fill="#E04F5F", width=2)
                self._cut_indicator_ids.extend([oval_id, line1_id, line2_id])

    def _draw_drop_indicator(self):
        """Draw drop insertion line"""
        index = self.drop_indicator_index
        x, y, h = 0, 0, 0
        
        # Handle special case: Drop Target Section (end of a section)
        if self.drop_target_section:
             last_idx = self.drop_target_section.end_page - 1
             if 0 <= last_idx < len(self.layout.positions):
                 lx, ly, lw, lh = self.layout.positions[last_idx]
                 x = lx + lw - 11
                 y = ly
                 h = lh
             else:
                 return
        
        # Handle End of Document
        elif index == self.item_count and self.item_count > 0:
             lx, ly, lw, lh = self.layout.positions[-1]
             x = lx + lw - 11
             y = ly
             h = lh
             
        # Handle Insertion between items (or at start)
        elif 0 <= index < self.item_count:
             # Draw at left edge of item 'index'
             if index < len(self.layout.positions):
                 lx, ly, lw, lh = self.layout.positions[index]
                 # Center on gap before item
                 x = lx - 14 # gap center (lx-1.5) - 12.5 (half img width) -> approx lx-14
                 y = ly
                 h = lh
             else:
                 return
        else:
            return

        # Draw the line
        line_width = 26
        line_height = h
        
        line_img = Image.new('RGBA', (line_width, line_height), (234, 234, 250, 180))
        line_photo = ImageTk.PhotoImage(line_img)
        
        self._drop_line_refs.append(line_photo)
        self.canvas.create_image(x, y, image=line_photo, anchor="nw")

    def _draw_item_smart(self, index: int):
        """
        Smart Draw - Dibuja o actualiza un item reutilizando objetos existentes.
        Separa el dibujo en:
        - Capa Base (imagen/placeholder): Se crea una vez, se mueve con coords()
        - Capa Overlay (selección, hover, marcas): Se recrea cada frame (es barato)
        """
        if index >= len(self.layout.positions):
            return
            
        x, y, w, h = self.layout.positions[index]
        
        # Inicializar tracking para este item si no existe
        if index not in self._drawn_items:
            self._drawn_items[index] = {}
        
        item_data = self._drawn_items[index]
        
        # === CAPA BASE ===
        # Verificar si ya tenemos un objeto base para este índice
        base_id = item_data.get("base")
        
        if self.box_mode:
            # Modo box: Smart Redraw optimizado
            # Solo redibujar la base si no existe o si el estado del box cambió
            box = self.get_box_at(index)
            if not box:
                return
            
            # Verificar si necesitamos redibujar la base
            cached_state = item_data.get("_box_state")
            current_state = (box.state, box.progress if box.state.name == "LOADING" else 0)
            
            if base_id is None or cached_state != current_state:
                # Eliminar TODOS los objetos anteriores de este item para redibujado limpio
                self._delete_item_objects(index)
                
                # Dibujar nueva base y guardar estado
                self._draw_box_base(index)
                item_data["_box_state"] = current_state
            
            # Dibujar overlays (hover, selección, brackets) - siempre se recrean
            self._draw_box_overlays(index)
            return
        
        # Modo páginas: optimización Smart Redraw
        if base_id is not None:
            # Ya existe un objeto base - verificar si podemos reutilizarlo
            try:
                obj_type = self.canvas.type(base_id)
                
                if index in self.images:
                    # Tenemos imagen cacheada
                    if obj_type == "image":
                        # Mover la imagen existente a la nueva posición
                        self.canvas.coords(base_id, x, y)
                        # Actualizar la imagen si cambió
                        self.canvas.itemconfig(base_id, image=self.images[index])
                    else:
                        # Era un rectángulo placeholder, reemplazar con imagen
                        self.canvas.delete(base_id)
                        base_id = self.canvas.create_image(x, y, image=self.images[index], anchor="nw")
                        item_data["base"] = base_id
                elif obj_type == "rectangle":
                    # Mover el rectángulo placeholder
                    self.canvas.coords(base_id, x, y, x+w, y+h)
                    # Iniciar render async si no está pendiente
                    if index not in self._pending_renders:
                        self._render_page_async(index, self.thumbnail_size)
                else:
                    # Tipo desconocido, recrear
                    self.canvas.delete(base_id)
                    base_id = None
                    item_data["base"] = None
            except Exception:
                # El objeto ya no existe, recrear
                base_id = None
                item_data["base"] = None
        
        # Crear objeto base si no existe
        if base_id is None:
            if index in self.images:
                base_id = self.canvas.create_image(x, y, image=self.images[index], anchor="nw")
            else:
                base_id = self.canvas.create_rectangle(x, y, x+w, y+h, fill="#404040", outline="")
                if index not in self._pending_renders:
                    self._render_page_async(index, self.thumbnail_size)
            item_data["base"] = base_id
        
        # === CAPA OVERLAY (se recrea cada frame) ===
        size_key = (w, h)
        
        # Selección (overlay azul) - usar cache por tamaño
        if index in self.selected_indices:
            if size_key not in self._selection_overlay_cache:
                overlay = Image.new('RGBA', (w, h), (31, 106, 165, 80))
                self._selection_overlay_cache[size_key] = ImageTk.PhotoImage(overlay)
            overlay_id = self.canvas.create_image(x, y, image=self._selection_overlay_cache[size_key], anchor="nw")
            item_data["selection"] = overlay_id
        
        # Marca (X roja) - líneas simples, muy baratas
        if index in self.marked_indices:
            line_width = 4
            line1_id = self.canvas.create_line(x, y, x+w, y+h, fill="#E04F5F", width=line_width)
            line2_id = self.canvas.create_line(x+w, y, x, y+h, fill="#E04F5F", width=line_width)
            item_data["mark1"] = line1_id
            item_data["mark2"] = line2_id
        
        # Hover (overlay gris) - usar cache por tamaño
        if index == self.hover_item_index:
            if size_key not in self._hover_overlay_cache:
                hover_overlay = Image.new('RGBA', (w, h), (128, 128, 128, 60))
                self._hover_overlay_cache[size_key] = ImageTk.PhotoImage(hover_overlay)
            hover_id = self.canvas.create_image(x, y, image=self._hover_overlay_cache[size_key], anchor="nw")
            item_data["hover"] = hover_id
        
        # Brackets de selección
        if not self.cut_mode and self.hover_index == index and self.hover_side:
            if self.hover_side == "left":
                bracket_id = self.canvas.create_line(x+10, y, x, y, x, y+h, x+10, y+h, fill="#1F6AA5", width=3)
                self._bracket_ids.append(bracket_id)
            elif self.hover_side == "right":
                bracket_id = self.canvas.create_line(x+w-10, y, x+w, y, x+w, y+h, x+w-10, y+h, fill="#1F6AA5", width=3)
                self._bracket_ids.append(bracket_id)

    def _draw_item(self, index: int):
        """Draw a single item (page or box depending on mode) - Legacy method"""
        if self.box_mode:
            self._draw_box(index)
        else:
            self._draw_page(index)
    
    def _draw_page(self, index: int):
        """Draw a single page thumbnail - OPTIMIZED with async rendering"""
        x, y, w, h = self.layout.positions[index]
        
        # 1. Draw Image (async rendering for better performance)
        if index in self.images:
            # Image already cached - draw it
            self.canvas.create_image(x, y, image=self.images[index], anchor="nw")
        elif index in self._pending_renders:
            # Image is being rendered - show placeholder
            self.canvas.create_rectangle(x, y, x+w, y+h, fill="#404040", outline="")
            if self._placeholder_image:
                # Center placeholder in the cell
                px = x + (w - 106) // 2  # 106 is placeholder width
                py = y + (h - 150) // 2  # 150 is placeholder height
                self.canvas.create_image(px, py, image=self._placeholder_image, anchor="nw")
        else:
            # Start async render and show placeholder
            self.canvas.create_rectangle(x, y, x+w, y+h, fill="#404040", outline="")
            self._render_page_async(index, self.thumbnail_size)
            
        # 2. Draw Selection (blue tint overlay)
        if index in self.selected_indices:
            # Create semi-transparent blue overlay
            # Color: #1F6AA5 (31, 106, 165) with alpha 80
            overlay = Image.new('RGBA', (w, h), (31, 106, 165, 80))
            overlay_photo = ImageTk.PhotoImage(overlay)
            # Store reference
            self._overlay_refs[index] = overlay_photo
            self.canvas.create_image(x, y, image=overlay_photo, anchor="nw")

        # 3. Draw Marked Indicator (red X for marked pages, like V1)
        if index in self.marked_indices:
            # Draw red X across the page (like V1)
            # Color: #E04F5F (red)
            line_width = 4
            # Diagonal from top-left to bottom-right
            self.canvas.create_line(
                x, y, x+w, y+h,
                fill="#E04F5F",
                width=line_width
            )
            # Diagonal from top-right to bottom-left
            self.canvas.create_line(
                x+w, y, x, y+h,
                fill="#E04F5F",
                width=line_width
            )
        
        # 4. Draw Hover effect (gray overlay, visible on ALL pages including selected)
        if index == self.hover_item_index:
            # Create semi-transparent gray overlay
            # Gray color with alpha for hover effect - drawn AFTER selection so it's visible
            hover_overlay = Image.new('RGBA', (w, h), (128, 128, 128, 60))
            hover_photo = ImageTk.PhotoImage(hover_overlay)
            # Store reference
            self._overlay_refs[f"hover_{index}"] = hover_photo
            self.canvas.create_image(x, y, image=hover_photo, anchor="nw")
        
        # 5. Draw Selection Brackets (only if NOT in cut mode)
        if not self.cut_mode and self.hover_index == index and self.hover_side:
            if self.hover_side == "left":
                self.canvas.create_line(x+10, y, x, y, x, y+h, x+10, y+h, fill="#1F6AA5", width=3)
            elif self.hover_side == "right":
                self.canvas.create_line(x+w-10, y, x+w, y, x+w, y+h, x+w-10, y+h, fill="#1F6AA5", width=3)
    
    def _draw_box_base(self, index: int):
        """Draw the base layer of a document box (background, thumbnail, text) - CACHED"""
        from src.pdf.structure import BoxState
        
        if index >= len(self.layout.positions):
            return
            
        x, y, w, h = self.layout.positions[index]
        box = self.get_box_at(index)
        
        if not box:
            return
        
        # Inicializar tracking si no existe
        if index not in self._drawn_items:
            self._drawn_items[index] = {}
        
        # Crear un grupo de IDs para la base (usamos una lista)
        base_ids = []
        
        # Background - adaptive colors
        box_colors = get_box_colors()
        bg_color = box_colors["bg"]
        if box.state == BoxState.FAILED:
            bg_color = box_colors["bg_failed"]
        elif box.state == BoxState.MARKED:
            bg_color = box_colors["bg_marked"]
        
        base_ids.append(self.canvas.create_rectangle(x, y, x+w, y+h, fill=bg_color, outline=box_colors["outline"], width=1))
        
        if box.thumbnail and box.state == BoxState.LOADED:
            if index not in self.box_images:
                thumb_source = box.thumbnail
                if hasattr(thumb_source, 'get_pixmap'):
                    try:
                        pix = thumb_source.get_pixmap(dpi=72)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    except Exception as e:
                        log.warning(f"Error rendering box thumbnail (document likely closed): {e}")
                        img = Image.new('RGB', (100, 140), color='#505050') # Fallback gray
                else:
                    # Si ya es una imagen PIL, hacemos una copia para no alterar la original al redimensionar
                    img = thumb_source.copy() if hasattr(thumb_source, 'copy') else thumb_source
                
                if img:
                    max_w = w - 20
                    max_h = h - 60
                    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                    self.box_images[index] = ImageTk.PhotoImage(img)
            
            if index in self.box_images:
                img_x = x + (w - self.box_images[index].width()) // 2
                img_y = y + 10
                base_ids.append(self.canvas.create_image(img_x, img_y, image=self.box_images[index], anchor="nw"))
        
        # Draw state indicator
        if box.state == BoxState.LOADING:
            if self.loading_placeholder:
                ph_x = x + (w - 80) // 2
                ph_y = y + (h - 80) // 2 - 30
                base_ids.append(self.canvas.create_image(ph_x, ph_y, image=self.loading_placeholder, anchor="nw"))
            
            base_ids.append(self.canvas.create_text(x + w//2, y + h//2 + 35, text="Cargando...",
                                  fill=box_colors["loading_text"], font=("Segoe UI", 9)))
            
            bar_x = x + 10
            bar_y = y + h - 40
            bar_w = w - 20
            bar_h = 8
            
            base_ids.append(self.canvas.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, 
                                        fill=box_colors["bar_bg"], outline=""))
            
            progress_w = int(bar_w * box.progress)
            if progress_w > 0:
                base_ids.append(self.canvas.create_rectangle(bar_x, bar_y, bar_x + progress_w, bar_y + bar_h,
                                            fill="#1F6AA5", outline=""))
            
            pct_text = f"{int(box.progress * 100)}%"
            base_ids.append(self.canvas.create_text(x + w//2, bar_y + bar_h + 10, text=pct_text,
                                  fill=box_colors["text_secondary"], font=("Segoe UI", 8)))
        
        elif box.state == BoxState.FAILED:
            base_ids.append(self.canvas.create_text(x + w//2, y + h//2 - 10, text="↻", 
                                  fill="#E04F5F", font=("Segoe UI", 48, "bold")))
            base_ids.append(self.canvas.create_text(x + w//2, y + h//2 + 35, text="Click para reintentar",
                                  fill="#E04F5F", font=("Segoe UI", 9)))
        
        elif box.state == BoxState.QUEUED:
            icon_id = self.canvas.create_text(x + w//2, y + h//2, text="⏳",
                                  fill="#E0A04F", font=("Segoe UI", 36))
            base_ids.append(icon_id)
            icon_bbox = self.canvas.bbox(icon_id)
            text_y = icon_bbox[3] + 5 if icon_bbox else (y + h//2 + 35)
            base_ids.append(self.canvas.create_text(x + w//2, text_y, text="En cola...",
                                  fill="#E0A04F", font=("Segoe UI", 9), anchor="n"))

        elif box.state == BoxState.MARKED:
            line_width = 4
            margin = 10
            base_ids.append(self.canvas.create_line(x + margin, y + margin, x + w - margin, y + h - margin,
                                  fill="#E04F5F", width=line_width))
            base_ids.append(self.canvas.create_line(x + w - margin, y + margin, x + margin, y + h - margin,
                                  fill="#E04F5F", width=line_width))
        
        # Draw name and page count
        text_y = y + h - 25
        name_text = box.name
        if len(name_text) > 20:
            name_text = name_text[:17] + "..."
        
        base_ids.append(self.canvas.create_text(x + w//2, text_y, text=name_text,
                              fill=box_colors["text"], font=("Segoe UI", 10)))
        
        if box.state == BoxState.LOADED and box.pages:
            page_count_text = f"{len(box.pages)}p"
            base_ids.append(self.canvas.create_text(x + w//2, text_y + 15, text=page_count_text,
                                  fill=box_colors["text_secondary"], font=("Segoe UI", 9)))
        
        # Guardar todos los IDs de la base
        self._drawn_items[index]["base"] = base_ids[0] if base_ids else None
        self._drawn_items[index]["_base_ids"] = base_ids

    def _draw_box_overlays(self, index: int):
        """Draw overlay layer of a document box (selection, hover, brackets) - RECREATED each frame"""
        if index >= len(self.layout.positions):
            return
            
        x, y, w, h = self.layout.positions[index]
        
        if index not in self._drawn_items:
            self._drawn_items[index] = {}
        
        item_data = self._drawn_items[index]
        size_key = (w, h)
        
        # Selection overlay - usar cache por tamaño
        if index in self.selected_indices:
            if size_key not in self._selection_overlay_cache:
                overlay = Image.new('RGBA', (w, h), (31, 106, 165, 60))
                self._selection_overlay_cache[size_key] = ImageTk.PhotoImage(overlay)
            overlay_id = self.canvas.create_image(x, y, image=self._selection_overlay_cache[size_key], anchor="nw")
            item_data["selection"] = overlay_id
        
        # Hover effect - usar cache por tamaño
        if index == self.hover_item_index:
            if size_key not in self._hover_overlay_cache:
                hover_overlay = Image.new('RGBA', (w, h), (128, 128, 128, 40))
                self._hover_overlay_cache[size_key] = ImageTk.PhotoImage(hover_overlay)
            hover_id = self.canvas.create_image(x, y, image=self._hover_overlay_cache[size_key], anchor="nw")
            item_data["hover"] = hover_id

        # Selection brackets - líneas simples, muy baratas
        if not self.cut_mode and self.hover_index == index and self.hover_side:
            if self.hover_side == "left":
                bracket_id = self.canvas.create_line(x + 10, y, x, y, x, y + h, x + 10, y + h, fill="#1F6AA5", width=3)
                self._bracket_ids.append(bracket_id)
            elif self.hover_side == "right":
                bracket_id = self.canvas.create_line(x + w - 10, y, x + w, y, x + w, y + h, x + w - 10, y + h, fill="#1F6AA5", width=3)
                self._bracket_ids.append(bracket_id)

    def _draw_box(self, index: int):
        """Draw a document box (staging area) - Legacy method, calls base + overlays"""
        self._draw_box_base(index)
        self._draw_box_overlays(index)

    def _on_motion(self, event):
        """Handle hover effects"""
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        
        index = self.layout.get_item_at(cx, cy)
        
        # If no direct hit, try tolerant search for gap detection
        if index == -1:
            scroll_y = self.canvas.canvasy(0)
            view_h = self.canvas.winfo_height()
            start, end = self.layout.get_visible_range(scroll_y, view_h)
            
            for i in range(start, end):
                if i < len(self.layout.positions):
                    lx, ly, lw, lh = self.layout.positions[i]
                    if (lx - 20 <= cx <= lx + lw + 20) and (ly - 20 <= cy <= ly + lh + 20):
                        index = i
                        break
        
        needs_redraw = False
        
        # Update hover item (for gray overlay effect)
        if self.hover_item_index != index:
            self.hover_item_index = index
            needs_redraw = True
        
        # Handle Cut Mode (Gap detection)
        if self.cut_mode:
            new_gap = None
            if index != -1:
                x, y, w, h = self.layout.positions[index]
                center_x = x + w / 2
                
                if cx < center_x:
                    new_gap = index
                else:
                    new_gap = index + 1
            
            if new_gap is not None:
                if new_gap <= 0: 
                    new_gap = None
                elif new_gap >= self.item_count: 
                    new_gap = None
            
            if self.hover_gap != new_gap:
                self.hover_gap = new_gap
                self.hover_index = -1
                self.hover_side = None
                needs_redraw = True
                
        else:
            if self.hover_gap is not None:
                self.hover_gap = None
                needs_redraw = True

            if index != -1:
                x, y, w, h = self.layout.positions[index]
                on_left = (cx - x) < 20
                on_right = (x + w - cx) < 20
                new_side = "left" if on_left else "right" if on_right else None
                
                if self.hover_index != index or self.hover_side != new_side:
                    self.hover_index = index
                    self.hover_side = new_side
                    needs_redraw = True
            else:
                if self.hover_index != -1:
                    self.hover_index = -1
                    self.hover_side = None
                    needs_redraw = True
                
        if needs_redraw:
            self.redraw()

    def _start_drag_fan(self):
        """
        Inicia el efecto de abanico obteniendo las miniaturas de las páginas o cajas seleccionadas.
        Usa un tamaño reducido para las miniaturas del abanico.
        """
        if not self.selected_indices:
            return
            
        # Tamaño para las miniaturas del abanico (usar constante global)
        fan_thumb_size = FAN_THUMB_SIZE
        thumbnails = []
        selected_sorted = sorted(self.selected_indices)

        if self.box_mode:
            # Modo cajas: obtener miniaturas de los objetos DocumentBox
            for idx in selected_sorted:
                if idx < len(self.document_boxes):
                    box = self.document_boxes[idx]
                    # Solo usar si tiene thumbnail
                    if box.thumbnail: 
                        try:
                            # Obtener imagen PIL (similar a _draw_box_base)
                            thumb_source = box.thumbnail
                            img = None
                            if hasattr(thumb_source, 'get_pixmap'):
                                # Es un objeto PyMuPDF o similar
                                try:
                                    pix = thumb_source.get_pixmap(dpi=72)
                                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                except Exception:
                                    continue
                            else:
                                # Asumir PIL Image
                                img = thumb_source.copy() if hasattr(thumb_source, 'copy') else thumb_source
                            
                            if img:
                                # Redimensionar si es muy grande para el efecto (optimización)
                                if img.height > fan_thumb_size * 2: # Si es mucho más grande
                                    aspect = img.width / img.height
                                    new_h = fan_thumb_size
                                    new_w = int(new_h * aspect)
                                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                                # Asegurar que es RGBA
                                if img.mode != 'RGBA':
                                    img = img.convert('RGBA')
                                thumbnails.append(img)
                        except Exception as e:
                            log.debug(f"Error getting box thumbnail for fan: {e}")
        else:
            # Modo páginas: usar callback para obtener miniaturas
            if not self.on_request_image:
                return

            for idx in selected_sorted:
                try:
                    # Solicitar imagen a tamaño reducido
                    pil_img = self.on_request_image(idx, fan_thumb_size)
                    if pil_img:
                        # Asegurar que es RGBA para transparencia
                        if pil_img.mode != 'RGBA':
                            pil_img = pil_img.convert('RGBA')
                        thumbnails.append(pil_img)
                except Exception as e:
                    log.debug(f"Error getting thumbnail for fan effect, page {idx}: {e}")
        
        if thumbnails:
            self.drag_fan.start(thumbnails)

    def _on_leave(self, event):
        """Handle mouse leaving canvas - clear hover effects"""
        if self.hover_item_index != -1:
            self.hover_item_index = -1
            self.redraw()

    def _on_click(self, event):
        """Handle single click - Selection"""
        # Close any active menu
        if hasattr(self, 'context_menu'):
            try:
                self.context_menu.unpost()
            except: pass
            
        self.canvas.focus_set()
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        
        # Check for left-click on section headers (Continuous Mode) - MANUAL CHECK
        if self.continuous_mode and not self.box_mode:
             fuzz = 5
             items = self.canvas.find_overlapping(cx - fuzz, cy - fuzz, cx + fuzz, cy + fuzz)
             for item_id in items:
                 if item_id in self._header_items:
                     section = self._header_items[item_id]
                     # Call rename logic directly
                     if self.on_header_rename_request:
                         self.on_header_rename_request(section)
                     elif hasattr(self.parent, 'rename_section'):
                         self.parent.rename_section(section)
                     return

        index = self.layout.get_item_at(cx, cy)
        
        # Store drag start position
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.drag_active = False
        
        # Global check for cut mode first
        if self.cut_mode and self.hover_gap is not None:
             if self.on_split_request:
                 self.on_split_request(self.hover_gap)
             return

        if index != -1:
            # Normal bracket detection (only if NOT in cut mode)
            if not self.cut_mode and self.hover_index == index and self.hover_side:
                # Bracket click
                if self.bracket_start is None:
                    # First bracket click - set start AND select item for visual feedback
                    self.bracket_start = index
                    self.selected_indices = {index}
                    if self.on_selection_change:
                        self.on_selection_change()
                    self.redraw()
                else:
                    # Second bracket click - complete range (works for boxes and pages)
                    start = min(self.bracket_start, index)
                    end = max(self.bracket_start, index)
                    self.selected_indices = set(range(start, end + 1))
                    self.bracket_start = None
                    if self.on_selection_change:
                        self.on_selection_change()
                    self.redraw()
                return


            # Check for Box Rename Click (Bottom area of box)
            if self.box_mode and index != -1:
                x, y, w, h = self.layout.positions[index]
                # If click is in the bottom 40 pixels (name area)
                if cy > y + h - 40:
                    if hasattr(self, 'on_box_rename_request') and self.on_box_rename_request:
                        self.on_box_rename_request(index)
                        return

            # Normal click
            # If clicking on already selected item, don't deselect (allow drag) and skip callbacks
            if index in self.selected_indices:
                self.pending_click_index = index
                self.pending_click_event = event
                return
            
            # Click on unselected item - clear bracket_start and select single
            self.bracket_start = None
            self.selected_indices = {index}
            self.redraw()
            if self.on_selection_change:
                self.on_selection_change()
            
            # Call on_click callback if set (for opening editor)
            if self.on_click:
                self.on_click(index, event)

    def _on_double_click(self, event):
        """Handle double click - Open Editor"""
        canvas_y = self.canvas.canvasy(event.y)
        index = self.layout.get_item_at(event.x, canvas_y)
        
        if index != -1:
            if self.on_double_click:
                self.on_double_click(index)

    def _on_ctrl_click(self, event):
        """Handle Ctrl+Click"""
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        index = self.layout.get_item_at(cx, cy)
        if index != -1:
            if index in self.selected_indices:
                self.selected_indices.remove(index)
            else:
                self.selected_indices.add(index)
            self.redraw()
            if self.on_selection_change:
                self.on_selection_change()

    def _on_shift_click(self, event):
        """Handle Shift+Click"""
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        index = self.layout.get_item_at(cx, cy)
        if index != -1 and self.selected_indices:
            last = list(self.selected_indices)[-1]
            start = min(last, index)
            end = max(last, index)
            for i in range(start, end + 1):
                self.selected_indices.add(i)
            self.redraw()
            if self.on_selection_change:
                self.on_selection_change()

    def _on_right_click_event(self, event):
        """Handle Right Click"""
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        
        # Check for right-click on section headers (Continuous Mode)
        if self.continuous_mode and not self.box_mode:
            fuzz = 5
            items = self.canvas.find_overlapping(cx - fuzz, cy - fuzz, cx + fuzz, cy + fuzz)
            
            for item_id in items:
                if item_id in self._header_items:
                    section = self._header_items[item_id]
                    log.info(f"Right-click header hit: {section.title}")
                    
                    if self.on_header_right_click:
                        class EventMock:
                            def __init__(self, x_root, y_root):
                                self.x_root = x_root
                                self.y_root = y_root
                        
                        mock = EventMock(event.x_root, event.y_root)
                        self.after(50, lambda s=section, m=mock: self.on_header_right_click(s, m))
                    return
        
        index = self.layout.get_item_at(cx, cy)
        # Always show context menu, even in empty space (index = -1)
        if self.on_right_click:
            self.on_right_click(index, event)

    def _on_drag(self, event):
        """Handle drag motion"""
        # Check if moved enough to start drag (5px threshold)
        dx = abs(event.x - self.drag_start_x)
        dy = abs(event.y - self.drag_start_y)
        
        if not self.drag_active and (dx > 5 or dy > 5):
            # Start drag
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
            index = self.layout.get_item_at(cx, cy)
            self.pending_click_index = None
            self.pending_click_event = None
            
            if index != -1 and index in self.selected_indices:
                self.drag_active = True
                self.drag_start_index = index
                
                # Iniciar efecto de abanico con las miniaturas seleccionadas
                self._start_drag_fan()
                
                if self.on_drag_start:
                    self.on_drag_start(index, event)
        
        handled_drag = False
        if self.drag_active:
            # Actualizar posición del abanico
            self.drag_fan.update_position(event.x, event.y)
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
            index = self.layout.get_item_at(cx, cy)
            
            # Reset explicit section target
            self.drop_target_section = None
            
            # Handle drop at end of SECTIONS or DOCUMENT
            if index == -1 and self.item_count > 0:
                # 1. Check Document End
                lx, ly, lw, lh = self.layout.positions[-1]
                if cy > ly + lh:
                    index = self.item_count
                elif cy >= ly and cx > lx + lw / 2:
                    index = self.item_count
                
                # 2. Check Section Ends (if not doc end)
                # Iterate sections to see if we are at the end of one
                if index == -1 and self.sections:
                    for section in self.sections:
                        # Get last page of section
                        last_page_idx = section.end_page - 1
                        if 0 <= last_page_idx < len(self.layout.positions):
                            px, py, pw, ph = self.layout.positions[last_page_idx]
                            # Check if in the same row and to the right
                            if py <= cy <= py + ph and cx > px + pw:
                                # We are to the right of this section's last item
                                index = section.end_page
                                self.drop_target_section = section
                                break
            
            # Update drop indicator
            # We need to refresh if index changed OR if drop_target_section changed
            
            # Calculate visual indicator index (suppress if using special section target)
            visual_indicator = index
            if self.drop_target_section:
                visual_indicator = -1
                
            if index != -1 and (visual_indicator != self.drop_indicator_index or getattr(self, '_last_drop_section', None) != self.drop_target_section):
                self.drop_indicator_index = visual_indicator
                self._last_drop_section = self.drop_target_section
                self.redraw()
            
            if self.on_drag_motion and index != -1:
                self.on_drag_motion(index, event)

    def _on_release(self, event):
        """Handle drag end"""
        handled_drag = False
        if self.drag_active:
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
            index = self.layout.get_item_at(cx, cy)
            
            # Logic duplicated from _on_drag to ensure correct index on release
            self.drop_target_section = None
            
            if index == -1 and self.item_count > 0:
                lx, ly, lw, lh = self.layout.positions[-1]
                if cy > ly + lh:
                    index = self.item_count
                elif cy >= ly and cx > lx + lw / 2:
                    index = self.item_count
                    
                if index == -1 and self.sections:
                    for section in self.sections:
                        last_page_idx = section.end_page - 1
                        if 0 <= last_page_idx < len(self.layout.positions):
                            px, py, pw, ph = self.layout.positions[last_page_idx]
                            if py <= cy <= py + ph and cx > px + pw:
                                index = section.end_page
                                self.drop_target_section = section
                                break
            
            if self.on_drag_end and index != -1:
                self.on_drag_end(index, event)
            
            # Reset drag state
            self.drag_active = False
            self.drop_indicator_index = -1
            self.drop_target_section = None
            
            # Detener efecto de abanico
            self.drag_fan.stop()
            
            self.redraw()
            handled_drag = True

        if (not handled_drag) and self.pending_click_index is not None:
            if self.on_click:
                self.on_click(self.pending_click_index, self.pending_click_event or event)
            self.pending_click_index = None
            self.pending_click_event = None
