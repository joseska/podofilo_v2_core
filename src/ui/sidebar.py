import customtkinter as ctk
import tkinter as tk
from typing import List, Callable, Optional
from PIL import Image, ImageTk, ImageDraw, ImageFont
import logging

from src.pdf.structure import Section
from src.ui.theme import get_theme

log = logging.getLogger(__name__)

def get_sidebar_colors():
    """Get sidebar colors based on current appearance mode - uses macOS theme"""
    theme = get_theme()
    return {
        "bg": theme.SIDEBAR_BG,
        "canvas_bg": theme.SIDEBAR_ITEM_BG,
        "colors": [theme.SIDEBAR_ITEM_BG, theme.BG_TERTIARY],
        "text": theme.TEXT_PRIMARY,
        "text_secondary": theme.TEXT_SECONDARY,
        "border": theme.BORDER_SUBTLE
    }

class RotatedLabel(ctk.CTkLabel):
    """Label with vertical text (rotated 90 degrees)"""
    def __init__(self, parent, text: str, **kwargs):
        super().__init__(parent, text="", **kwargs)
        self._text_content = text
        self._color = kwargs.get("text_color", "white")
        self._update_image()
        
    def configure(self, **kwargs):
        if "text" in kwargs:
            self._text_content = kwargs.pop("text")
            self._update_image()
        super().configure(**kwargs)
        
    def _update_image(self):
        # Create image with text
        # This is a simplified approximation
        font_size = 12
        font = ImageFont.load_default() # capable of better fonts if path provided
        
        # Measure text
        dummy_img = Image.new('RGBA', (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        bbox = draw.textbbox((0, 0), self._text_content, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        
        # Create image
        img = Image.new('RGBA', (w + 10, h + 10), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((5, 5), self._text_content, font=font, fill=self._color)
        
        # Rotate
        rotated = img.rotate(90, expand=True)
        
        self._image = ImageTk.PhotoImage(rotated)
        super().configure(image=self._image)

class SectionWidget(ctk.CTkFrame):
    """Visual representation of a section in the sidebar"""
    def __init__(self, parent, section: Section, height: int, on_click: Callable, on_right_click: Callable):
        super().__init__(parent, corner_radius=0)
        self.section = section
        self.on_click = on_click
        self.on_right_click = on_right_click
        
        # Determine color based on even/odd or selection?
        # For now just a simple frame
        self.configure(fg_color="transparent", border_width=1, border_color="#404040")
        
        # Vertical Text
        # Using standard Label with \n for now as simple fallback if rotation is tricky
        # or try the canvas approach. 
        # Requirement: "rotados 90°".
        # Let's use a Canvas to draw the text rotated.
        
        colors = get_sidebar_colors()
        self.canvas = tk.Canvas(self, bg=colors["canvas_bg"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # Bind events
        self.canvas.bind("<Button-1>", lambda e: self.on_click(self.section))
        self.canvas.bind("<Button-3>", lambda e: self.on_right_click(self.section, e))
        
        self.draw_label()
        
    def draw_label(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        
        # Draw vertical text
        # We can use create_text with angle=90 (Tkinter 8.6+ supports angle)
        self.canvas.create_text(
            15, h/2,
            text=self.section.title,
            angle=90,
            fill=get_sidebar_colors()["text"],
            font=("Segoe UI", 10),
            anchor="center"
        )
        
        # Draw page count indicator
        self.canvas.create_text(
            15, 15,
            text=str(self.section.page_count),
            fill="#aaaaaa",
            font=("Segoe UI", 8),
            anchor="n"
        )

class SectionSidebar(ctk.CTkScrollableFrame):
    """Sidebar displaying sections"""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=40, **kwargs)
        
        self.sections: List[Section] = []
        self.callbacks = {}
        
    def set_sections(self, sections: List[Section], section_bounds: dict, total_height: int):
        """
        Update sidebar content
        sections: List of sections
        section_bounds: Dict[int, (start_y, end_y)] from grid layout
        total_height: Total height of grid content
        """
        # Clear current
        for widget in self.winfo_children():
            widget.destroy()
            
        self.sections = sections
        
        # The sidebar needs to sync with the grid scroll. 
        # However, standard ScrollableFrame has its own scroll handling.
        # 
        # Alternative approach: 
        # The sidebar shouldn't be a ScrollableFrame if we want it to sync perfectly 
        # with the grid's canvas. It should be a Canvas itself that mirrors the grid's coordinates.
        
        # BUT, implementing a synced scroll sidebar is complex.
        # If we want "sincronizada con el scroll", it's best if it's just drawn ON the grid 
        # or is a separate canvas controlled by the same scrollbar.
        pass

class SyncedSidebar(tk.Canvas):
    """
    Sidebar that syncs exactly with the VirtualGrid.
    Renders section indicators matching the grid's Y coordinates.
    """
    def __init__(self, parent, **kwargs):
        # Ensure width is handled correctly
        if 'width' in kwargs:
            kwargs.pop('width')
            
        colors = get_sidebar_colors()
        # Sidebar integrado: sin borde alrededor (para evitar líneas arriba/abajo/izquierda).
        # La separación con el contenido la dibujamos como una única línea a la derecha.
        super().__init__(
            parent,
            width=40,
            bg=colors["bg"],
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self.sections: List[Section] = []
        self.section_bounds: dict = {}
        self.on_section_click = None
        self.on_section_right_click = None
        self.on_section_reorder = None
        self.on_section_drag_indicator = None
        
        # Estado interno para diferenciar click vs drag.
        # Esto permite arrastrar una sección para reordenarla sin disparar el renombrado.
        self._pressed_section_idx: int = -1
        self._press_y: float = 0.0
        self._dragging: bool = False
        self._drag_threshold_px: int = 6
        
        # Events
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Button-3>", self._on_right_click)
        
    def update_layout(self, sections: List[Section], section_bounds: dict, total_height: int):
        self.sections = sections
        self.section_bounds = section_bounds
        
        # Update scroll region to match grid
        self.configure(scrollregion=(0, 0, 40, total_height))
        self.redraw()
        
    def redraw(self):
        self.delete("all")
        
        # Draw each section
        theme = get_sidebar_colors()
        colors = theme["colors"]
        
        for i, section in enumerate(self.sections):
            if i not in self.section_bounds:
                continue
                
            y1, y2 = self.section_bounds[i]
            h = y2 - y1
            
            # Background
            color = colors[i % 2]
            # Sin contorno por item: se ve más "plano" e integrado, el separador del canvas ya delimita
            self.create_rectangle(0, y1, 40, y2, fill=color, outline="")
            
            # Text (rotated)
            # Only draw if height is sufficient
            if h > 40:
                # Truncate title if too long
                title = section.title
                if len(title) > 20:
                    title = title[:17] + "..."
                    
                self.create_text(
                    20, y1 + h/2,
                    text=title,
                    angle=90,
                    fill=get_sidebar_colors()["text"],
                    font=("Segoe UI", 9),
                    anchor="center"
                )
            
            # Page count
            self.create_text(
                20, y1 + 10,
                text=str(section.page_count),
                fill=theme["text_secondary"],
                font=("Segoe UI", 8),
                anchor="n"
            )

        # Línea separadora única a la derecha (estilo Windows Fotos)
        max_y = 0
        for bounds in self.section_bounds.values():
            max_y = max(max_y, bounds[1])
        max_y = max(max_y, self.winfo_height())
        self.create_line(39, 0, 39, max_y, fill=theme["border"])
        
        # Nota: el indicador de drag se dibuja dinámicamente durante el arrastre.
        # En cada redraw limpiamos todo, así que aquí no hay que gestionar su borrado.
            
    def _on_press(self, event):
        # Guardamos qué sección se pulsó y la coordenada inicial.
        # Si el usuario mueve el ratón más de un umbral, lo interpretamos como arrastre.
        y = self.canvasy(event.y)
        self._pressed_section_idx = self._get_section_at(y)
        self._press_y = y
        self._dragging = False
        # Quitar cualquier indicador anterior (por seguridad ante eventos interrumpidos).
        self.delete("drag_indicator")
        if self.on_section_drag_indicator:
            self.on_section_drag_indicator(None)
    
    def _on_drag_motion(self, event):
        if self._pressed_section_idx == -1:
            return
        
        y = self.canvasy(event.y)
        
        # Si todavía no estamos en modo drag, comprobamos si supera el umbral.
        if not self._dragging:
            if abs(y - self._press_y) < self._drag_threshold_px:
                return
            self._dragging = True
        
        # Dibujar un indicador visual de dónde se insertaría la sección.
        insert_index = self._get_insert_index(y)
        y_line = self._get_insert_y_line(insert_index)
        self._draw_drag_indicator(y_line)
        if self.on_section_drag_indicator:
            self.on_section_drag_indicator(y_line)
    
    def _on_release(self, event):
        if self._pressed_section_idx == -1:
            return
        
        y = self.canvasy(event.y)
        section_idx = self._pressed_section_idx
        
        # Reset del estado de click/drag.
        self._pressed_section_idx = -1
        self._press_y = 0.0
        
        # Limpiar el indicador, si existe.
        self.delete("drag_indicator")
        if self.on_section_drag_indicator:
            self.on_section_drag_indicator(None)
        
        # Si hubo arrastre, pedimos reordenado. Si no, tratamos como click (renombrar).
        if self._dragging:
            self._dragging = False
            if not self.on_section_reorder:
                return
            
            insert_index = self._get_insert_index(y)
            if 0 <= section_idx < len(self.sections):
                self.on_section_reorder(self.sections[section_idx], insert_index)
            return
        
        self._dragging = False
        if section_idx != -1 and self.on_section_click and 0 <= section_idx < len(self.sections):
            self.on_section_click(self.sections[section_idx])
            
    def _on_right_click(self, event):
        y = self.canvasy(event.y)
        section_idx = self._get_section_at(y)
        if section_idx != -1 and self.on_section_right_click:
            self.on_section_right_click(self.sections[section_idx], event)
            
    def _get_section_at(self, y: float) -> int:
        for i, bounds in self.section_bounds.items():
            if bounds[0] <= y <= bounds[1]:
                return i
        return -1

    def _get_insert_index(self, y: float) -> int:
        """Calcular en qué posición de la lista se insertaría una sección al soltar en la coordenada y."""
        idx = self._get_section_at(y)
        if idx == -1:
            return len(self.sections)
        
        if idx not in self.section_bounds:
            return len(self.sections)
        
        y1, y2 = self.section_bounds[idx]
        mid = (y1 + y2) / 2
        # Si sueltas en la mitad superior, insertamos antes; en la inferior, después.
        return idx if y <= mid else idx + 1

    def _get_insert_y_line(self, insert_index: int) -> float:
        """Calcular la coordenada Y (en coordenadas del canvas) para dibujar el indicador de inserción."""
        # Calcular Y del indicador: el inicio de la sección destino o el final del último bloque.
        if insert_index <= 0:
            return 0
        if insert_index >= len(self.sections):
            y_line = 0
            for bounds in self.section_bounds.values():
                y_line = max(y_line, bounds[1])
            return y_line
        
        if insert_index in self.section_bounds:
            return self.section_bounds[insert_index][0]
        
        # Fallback: buscar el bound más cercano.
        y_line = 0
        for i, bounds in self.section_bounds.items():
            if i >= insert_index:
                y_line = bounds[0]
                break
        return y_line

    def _draw_drag_indicator(self, y_line: float):
        """Dibuja una línea horizontal para previsualizar el punto de inserción durante el drag."""
        self.delete("drag_indicator")
        
        theme = get_sidebar_colors()
        # Línea visible pero discreta (usa el color de borde del sidebar).
        self.create_line(2, y_line, 38, y_line, fill=theme["border"], width=2, tags="drag_indicator")
