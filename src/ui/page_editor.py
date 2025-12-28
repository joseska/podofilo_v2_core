"""
Page Editor Window - Full screen page viewer/editor
"""
import logging
import customtkinter as ctk
from tkinter import Canvas, Menu
from PIL import Image, ImageTk
from typing import Optional, Callable

from src.ui.theme import get_theme

log = logging.getLogger(__name__)


class PageEditorWindow(ctk.CTkFrame):
    """Full screen page editor (embedded in main window)"""
    
    def __init__(self, parent, page_index: int, get_page_image: Callable, section_name: str = "", on_close: Optional[Callable] = None):
        """
        Initialize page editor
        
        Args:
            parent: Parent frame
            page_index: Index of page to edit
            get_page_image: Callback to get page image at high DPI
            section_name: Name of the section this page belongs to
            on_close: Optional callback when editor closes
        """
        theme = get_theme()
        super().__init__(parent, fg_color=theme.BG_PRIMARY)
        
        self.page_index = page_index
        self.get_page_image = get_page_image
        self.section_name = section_name
        self.on_close_callback = on_close
        self.parent = parent
        
        # Zoom state
        self.zoom_level = 1.0  # 1.0 = fit to window
        self.min_zoom = 0.1
        self.max_zoom = 5.0
        self.zoom_step = 0.1
        
        # Callbacks for PDF operations
        self.on_add_numbering = None  # Callback to add page numbering to all pages
        self.on_remove_numbering = None  # Callback to remove page numbering
        self.on_number_current_page = None  # Callback to number only current page
        self.on_customize_format = None  # Callback to customize numbering format
        self.on_change_position = None  # Callback to change numbering position
        self.on_close_from_menu = None  # Callback to close editor from menu (different from on_close_callback)
        self.on_split_section = None  # Callback to split section at current page
        
        # Setup UI
        self._setup_ui()
        
        # Load and display page
        self._load_page()
        
        # Bind ESC key to close (needs to be on parent window)
        # We'll handle this in main_window instead
        
        log.info(f"Page editor opened for page {page_index}")
    
    def _setup_ui(self):
        """Setup UI components"""
        # Pack this frame first
        self.pack(fill="both", expand=True)
        
        # Create frame for canvas and scrollbars (full space for visualization)
        theme = get_theme()
        canvas_frame = ctk.CTkFrame(self, fg_color=theme.BG_PRIMARY)
        canvas_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Canvas for page display
        self.canvas = Canvas(
            canvas_frame,
            bg=theme.CANVAS_BG,
            highlightthickness=0
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        
        # Scrollbars
        self.v_scrollbar = ctk.CTkScrollbar(canvas_frame, orientation="vertical", command=self.canvas.yview)
        self.v_scrollbar.grid(row=0, column=1, sticky="ns")
        
        self.h_scrollbar = ctk.CTkScrollbar(canvas_frame, orientation="horizontal", command=self.canvas.xview)
        self.h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        # Configure canvas scrolling
        self.canvas.configure(
            xscrollcommand=self.h_scrollbar.set,
            yscrollcommand=self.v_scrollbar.set
        )
        
        # Configure grid weights
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        
        # Bind resize to update display
        self.canvas.bind("<Configure>", self._on_resize)
        
        # Bind mouse wheel for scrolling (without Ctrl)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel_scroll)
        
        # Bind right-click for context menu
        self.canvas.bind("<Button-3>", self._show_context_menu)
        
        # Store image reference
        self.photo_image = None
        self.canvas_image_id = None
        self.section_label_id = None
        self.section_bg_id = None
        
        # Create context menu
        self._create_context_menu()
    
    def _load_page(self):
        """Load and display the page"""
        try:
            log.debug(f"Loading page {self.page_index} at 200 DPI")
            # Get high-resolution image (200 DPI for good quality)
            image = self.get_page_image(self.page_index, dpi=200)
            
            if image:
                log.debug(f"Image loaded successfully: {image.size}")
                self.original_image = image
                # Schedule display after widget is rendered
                self.after(10, self._display_image)
            else:
                log.error(f"Failed to load image for page {self.page_index}")
                
        except Exception as e:
            log.error(f"Error loading page {self.page_index}: {e}", exc_info=True)

    def show_page(self, page_index: int, section_name: str = ""):
        """Switch editor to a different page index"""
        # Only return early if index matches AND no new section name provided
        # This allows refreshing the title (e.g. after Split) even if staying on same page
        if page_index == self.page_index and not section_name:
            return

        self.page_index = page_index
        if section_name:
            self.section_name = section_name
            
        # Clear current canvas image while loading the new page
        if self.canvas_image_id:
            self.canvas.delete(self.canvas_image_id)
            self.canvas_image_id = None

        self.original_image = None
        self.photo_image = None
        self._load_page()
    
    def _display_image(self):
        """Display the image on canvas, fitted to window"""
        if not hasattr(self, 'original_image') or not self.original_image:
            log.warning("No original image to display")
            return
        
        # Get canvas size
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        log.debug(f"Canvas size: {canvas_width}x{canvas_height}")
        
        # Need valid dimensions
        if canvas_width <= 1 or canvas_height <= 1:
            # Canvas not ready yet, schedule retry
            log.debug("Canvas not ready, retrying in 50ms")
            self.after(50, self._display_image)
            return
        
        # Calculate scaling to fit image in canvas
        img_width, img_height = self.original_image.size
        
        # Calculate base scale to fit in window
        margin = 20
        scale_x = (canvas_width - margin) / img_width
        scale_y = (canvas_height - margin) / img_height
        base_scale = min(scale_x, scale_y)
        
        # Apply zoom level
        scale = base_scale * self.zoom_level
        
        # Calculate new size
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)
        
        # Limit zoom to canvas width (no horizontal scroll)
        if new_width > canvas_width - margin:
            # Recalculate to fit width
            scale = (canvas_width - margin) / img_width
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)
            # Update zoom level to reflect the actual zoom
            self.zoom_level = scale / base_scale
        
        # Resize image
        resized_image = self.original_image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS
        )
        
        # Convert to PhotoImage
        self.photo_image = ImageTk.PhotoImage(resized_image)
        
        # Clear previous image
        if self.canvas_image_id:
            self.canvas.delete(self.canvas_image_id)
        
        # Always center horizontally
        x = canvas_width // 2
        
        # Position vertically
        padding = 50
        if new_height < canvas_height:
            # Center vertically if image fits
            y = canvas_height // 2
            anchor = "center"
            scroll_height = canvas_height
        else:
            # Position at top with padding if image is taller
            y = padding
            anchor = "n"  # North anchor (top-center)
            scroll_height = new_height + padding * 2
        
        self.canvas_image_id = self.canvas.create_image(
            x, y,
            image=self.photo_image,
            anchor=anchor
        )
        
        # Update scroll region (no horizontal scroll)
        self.canvas.configure(scrollregion=(0, 0, canvas_width, scroll_height))
        
        # Show/hide scrollbars based on need
        if new_height > canvas_height:
            # Need vertical scroll
            self.v_scrollbar.grid()
        else:
            # No need for vertical scroll
            self.v_scrollbar.grid_remove()
        
        # Horizontal scrollbar always hidden (we limit zoom to width)
        self.h_scrollbar.grid_remove()
        
        log.debug(f"Image displayed: {new_width}x{new_height} (scale: {scale:.2f})")
        
        # Display Section Name (Top-Left)
        self._display_section_name()

    def _display_section_name(self):
        """Draw section name indicator in top-left corner"""
        # Clear previous
        if self.section_label_id:
            self.canvas.delete(self.section_label_id)
        if self.section_bg_id:
            self.canvas.delete(self.section_bg_id)
            
        if not self.section_name:
            return
            
        # Style
        padding_x = 10
        padding_y = 6
        x = 20
        y = 20
        
        # User requested changes
        font = ("Segoe UI", 12, "bold") # Smaller text
        text_color = "white"
        bg_color = "#444444" # Gray background (less intrusive)
        
        # Truncate text if needed (max 40% of window width)
        canvas_width = self.canvas.winfo_width()
        max_width = int(canvas_width * 0.4)
        
        # Import font measurement tool if needed, or use approximate char width
        # Simple truncation loop based on estimated char width is safer without tk.Font imports
        # Or better: let's use canvas.create_text with 'width' to wrap or ellipses manual
        
        display_text = self.section_name
        
        # Measure text width roughly or iteratively using a temp text item
        temp_id = self.canvas.create_text(0, 0, text=display_text, font=font, anchor="nw")
        bbox = self.canvas.bbox(temp_id)
        text_width = bbox[2] - bbox[0]
        self.canvas.delete(temp_id)
        
        if text_width > max_width and max_width > 50:
            # Truncate logic
            avg_char_width = text_width / len(display_text)
            max_chars = int(max_width / avg_char_width) - 3
            if max_chars < 1: max_chars = 1
            display_text = display_text[:max_chars] + "..."
        
        # Create text
        self.section_label_id = self.canvas.create_text(
            x + padding_x, y + padding_y,
            text=display_text,
            font=font,
            fill=text_color,
            anchor="nw"
        )
        
        # Get bounds
        bbox = self.canvas.bbox(self.section_label_id)
        if bbox:
            x1, y1, x2, y2 = bbox
            # Create background rectangle behind text
            self.section_bg_id = self.canvas.create_rectangle(
                x1 - padding_x, y1 - padding_y,
                x2 + padding_x, y2 + padding_y,
                fill=bg_color,
                outline="",
                tags="section_overlay"
            )
            # Raise text above background
            self.canvas.tag_raise(self.section_label_id)
    
    def _on_resize(self, event):
        """Handle window resize"""
        # Redisplay image to fit new size
        self._display_image()
    
    def _on_mouse_wheel_scroll(self, event):
        """Handle mouse wheel for vertical scrolling (without Ctrl)"""
        # Scroll vertically
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    
    def zoom_in(self, event=None):
        """Increase zoom level"""
        self.zoom_level = min(self.max_zoom, self.zoom_level + self.zoom_step)
        self._display_image()
        log.debug(f"Zoom in: {self.zoom_level:.1f}x")
    
    def zoom_out(self, event=None):
        """Decrease zoom level"""
        self.zoom_level = max(self.min_zoom, self.zoom_level - self.zoom_step)
        self._display_image()
        log.debug(f"Zoom out: {self.zoom_level:.1f}x")
    
    def zoom_reset(self, event=None):
        """Reset zoom to fit window"""
        self.zoom_level = 1.0
        self._display_image()
        log.debug("Zoom reset: 1.0x (fit to window)")
    
    def on_mouse_wheel(self, event):
        """Handle mouse wheel zoom with Ctrl"""
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
    
    def _on_add_numbering_click(self):
        """Handle click on numbering button"""
        if self.on_add_numbering:
            self.on_add_numbering()
        else:
            log.warning("No numbering callback set")
    
    def _on_remove_numbering_click(self):
        """Handle click on remove numbering button"""
        if self.on_remove_numbering:
            self.on_remove_numbering()
        else:
            log.warning("No remove numbering callback set")
    
    def _create_context_menu(self):
        """Create context menu for editor"""
        self.context_menu = Menu(self.canvas, tearoff=0)
        
        # Numeración submenu
        numbering_menu = Menu(self.context_menu, tearoff=0)
        numbering_menu.add_command(
            label="Añadir Numeración (T)",
            command=self._on_add_numbering_click
        )
        numbering_menu.add_command(
            label="Eliminar Numeración (Mayúsculas + T)",
            command=self._on_remove_numbering_click
        )
        numbering_menu.add_separator()
        numbering_menu.add_command(
            label="Personalizar Formato Numeración...",
            command=self._on_customize_format
        )
        numbering_menu.add_command(
            label="Cambiar Posición Numeración...",
            command=self._on_change_position
        )
        
        self.context_menu.add_cascade(label="Numeración", menu=numbering_menu)
        
        # Section operations
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="✂️ Dividir Sección Aquí (K)",
            command=self._on_split_section
        )
        
        # Otras opciones del editor
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Cerrar Editor (ESC)",
            command=self._on_close_from_menu
        )
    
    def _show_context_menu(self, event):
        """Show context menu at cursor position"""
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
    
    def _on_number_current_page(self):
        """Add numbering only to current page"""
        if self.on_number_current_page:
            self.on_number_current_page(self.page_index)
        else:
            log.warning("No number current page callback set")
    
    def _on_customize_format(self):
        """Show dialog to customize numbering format"""
        if self.on_customize_format:
            self.on_customize_format()
        else:
            log.warning("No customize format callback set")
    
    def _on_change_position(self):
        """Show dialog to change numbering position"""
        if self.on_change_position:
            self.on_change_position()
        else:
            log.warning("No change position callback set")
    
    def _on_split_section(self):
        """Split section at current page"""
        if self.on_split_section:
            self.on_split_section(self.page_index)
        else:
            log.warning("No split section callback set")
    
    def _on_close_from_menu(self):
        """Handle close from context menu"""
        # Use the specific menu close callback if set
        if self.on_close_from_menu:
            self.on_close_from_menu()
        else:
            # Fallback to regular close
            self.close()
    
    def close(self):
        """Close the editor"""
        log.info(f"Closing page editor for page {self.page_index}")
        
        # Call callback if provided
        if self.on_close_callback:
            self.on_close_callback()
        
        # Hide/destroy this frame
        self.pack_forget()
        self.destroy()
