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
        super().__init__(parent, width=40, bg=colors["bg"], highlightthickness=0, bd=0, **kwargs)
        self.sections: List[Section] = []
        self.section_bounds: dict = {}
        self.on_section_click = None
        self.on_section_right_click = None
        
        # Events
        self.bind("<Button-1>", self._on_click)
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
            self.create_rectangle(0, y1, 40, y2, fill=color, outline=theme["border"])
            
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
            
    def _on_click(self, event):
        y = self.canvasy(event.y)
        section_idx = self._get_section_at(y)
        if section_idx != -1 and self.on_section_click:
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
