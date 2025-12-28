"""
PDF Thumbnail Widget - V1 Style
Displays PDF page thumbnail with green bracket selection markers and drag-and-drop support
"""
import logging
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageFont
from typing import Callable, Optional
import tkinter as tk

log = logging.getLogger(__name__)

class ThumbnailWidget(ctk.CTkFrame):
    """Widget for displaying a single PDF page thumbnail (V1 style)"""
    
    def __init__(self, parent, page_idx: int, image: Image.Image, 
                 on_click: Optional[Callable] = None,
                 on_right_click: Optional[Callable] = None,
                 on_bracket_click: Optional[Callable] = None,
                 on_drag_start: Optional[Callable] = None,
                 on_drag_motion: Optional[Callable] = None,
                 on_drag_end: Optional[Callable] = None,
                 pdf_name: Optional[str] = None):
        """
        Initialize thumbnail widget
        
        Args:
            parent: Parent widget
            page_idx: Page index (0-indexed)
            image: PIL Image of the page
            on_click: Callback for left click
            on_right_click: Callback for right click
            on_bracket_click: Callback for bracket click (range selection)
            on_drag_start: Callback for drag start
            on_drag_motion: Callback for drag motion
            on_drag_end: Callback for drag end
            pdf_name: PDF filename to show on first page only
        """
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        
        self.page_idx = page_idx
        self.image = image
        self.on_click = on_click
        self.on_right_click = on_right_click
        self.on_bracket_click = on_bracket_click
        self.on_drag_start = on_drag_start
        self.on_drag_motion = on_drag_motion
        self.on_drag_end = on_drag_end
        self.selected = False
        self.show_left_bracket = False
        self.show_right_bracket = False
        
        # Drag state
        self.drag_active = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        
        # Add PDF name overlay if this is first page
        if pdf_name:
            image = self._add_pdf_name_overlay(image, pdf_name)
        
        # Create canvas for drawing image + brackets
        # V1 Style: Canvas is EXACTLY the size of the image
        # Brackets and borders are drawn OVER the image
        self.canvas = tk.Canvas(
            self,
            width=image.width,
            height=image.height,
            highlightthickness=0,
            bg="#242424"
        )
        self.canvas.pack()
        
        # Draw image at (0,0)
        self.photo = ImageTk.PhotoImage(image)
        self.image_id = self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        
        # Selection border (rectangle drawn over image)
        self.border_id = None
        
        # Bracket indicators (will be drawn on hover)
        self.left_bracket_id = None
        self.right_bracket_id = None
        
        # Bind events
        self.canvas.bind("<Button-1>", self._on_left_click)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<B1-Motion>", self._on_drag_motion_internal)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        
        # Initial appearance
        self._update_appearance()
    
    def update_size(self, width: int, height: int, rescale_image: bool = False):
        """Update widget size, optionally rescaling current image for speed"""
        self.canvas.configure(width=width, height=height)
        self.configure(width=width, height=height)
        
        if rescale_image and hasattr(self, 'image') and self.image and self.image.width > 1:
            # Fast resize of current image to match new size (preview)
            # This allows instant feedback while high-res loads in background
            
            # Calculate new dimensions preserving aspect ratio
            img_ratio = self.image.width / self.image.height
            
            # Target is to fit within width x height
            # But usually we just want to match the height (thumbnail_size)
            # and let width adjust, but the widget is fixed size?
            # The widget size passed here IS the target size (thumbnail_size)
            
            # We want to fit the image inside the square box
            target_w = width
            target_h = height
            
            if img_ratio > 1: # Landscape
                new_w = target_w
                new_h = int(target_w / img_ratio)
            else: # Portrait
                new_h = target_h
                new_w = int(target_h * img_ratio)
                
            # Use BILINEAR for speed (LANCZOS is too slow for realtime)
            resized = self.image.resize((new_w, new_h), Image.Resampling.BILINEAR)
            self.photo = ImageTk.PhotoImage(resized)
            self.canvas.itemconfig(self.image_id, image=self.photo)
            
            # Re-center image
            # self.canvas.coords(self.image_id, (width-new_w)//2, (height-new_h)//2) # If we wanted centering
            # But currently we anchor nw. Let's keep it simple for now.
            
            self._update_appearance()
        
    def set_image(self, image: Image.Image, pdf_name: Optional[str] = None):
        """Update displayed image"""
        self.image = image
        
        # Add PDF name overlay if needed
        if pdf_name:
            image = self._add_pdf_name_overlay(image, pdf_name)
            
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.itemconfig(self.image_id, image=self.photo)
        
        # Ensure canvas size matches image
        self.canvas.configure(width=image.width, height=image.height)
        self.configure(width=image.width, height=image.height)
        
        # Redraw overlays
        self._update_appearance()
        
    def clear_image(self):
        """Clear image content to save memory (virtualization)"""
        # Create a lightweight placeholder (1x1 pixel)
        # We keep the widget size but remove the heavy image content
        if hasattr(self, 'image') and self.image.width > 1:
            # Adaptive placeholder color
            mode = ctk.get_appearance_mode()
            placeholder_color = '#f0f0f0' if mode == "Light" else '#2b2b2b'
            placeholder = Image.new('RGB', (1, 1), color=placeholder_color)
            self.image = placeholder
            self.photo = ImageTk.PhotoImage(placeholder)
            self.canvas.itemconfig(self.image_id, image=self.photo)
            # Note: We DO NOT resize the widget/canvas here, 
            # we want it to keep occupying the same space in the grid

    def _add_pdf_name_overlay(self, image: Image.Image, pdf_name: str) -> Image.Image:
        """Add PDF name overlay to top-left corner (like V1)"""
        img_copy = image.copy()
        draw = ImageDraw.Draw(img_copy)

        
        try:
            font = ImageFont.truetype("arial.ttf", 10)
        except:
            font = ImageFont.load_default()
        
        text = pdf_name
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Semi-transparent background
        padding = 3
        draw.rectangle(
            [(0, 0), (text_width + padding * 2, text_height + padding * 2)],
            fill=(0, 0, 0, 180)
        )
        
        # Draw text
        draw.text((padding, padding), text, fill="white", font=font)
        
        return img_copy
    
    def _on_motion(self, event):
        """Handle mouse motion - show brackets on edges"""
        x = event.x
        width = self.canvas.winfo_width()
        
        # Check if near left or right edge (within 20 pixels)
        near_left = x < 20
        near_right = x > width - 20
        
        if near_left != self.show_left_bracket or near_right != self.show_right_bracket:
            self.show_left_bracket = near_left
            self.show_right_bracket = near_right
            self._draw_brackets()

    def _on_leave(self, event):
        """Hide brackets when mouse leaves"""
        if self.show_left_bracket or self.show_right_bracket:
            self.show_left_bracket = False
            self.show_right_bracket = False
            self._draw_brackets()

    def _draw_brackets(self):
        """Draw bracket indicators on edges (Corner style - V1)"""
        # Clear old brackets
        if self.left_bracket_id:
            self.canvas.delete(self.left_bracket_id)
            self.left_bracket_id = None
        if self.right_bracket_id:
            self.canvas.delete(self.right_bracket_id)
            self.right_bracket_id = None
            
        height = self.canvas.winfo_height()
        width = self.canvas.winfo_width()
        corner_len = 12
        line_width = 3  # Reduced from 4px
        color = "#1F6AA5"  # Podofilo Blue (V1 style)
        
        # Left bracket [ - Drawn OVER the image on the left edge
        if self.show_left_bracket:
            points = [
                corner_len, 1,          # Top-left end
                1, 1,                   # Top-left corner
                1, height-2,            # Bottom-left corner
                corner_len, height-2    # Bottom-left end
            ]
            self.left_bracket_id = self.canvas.create_line(
                points,
                width=line_width, fill=color, capstyle="projecting", joinstyle="miter"
            )
            
        # Right bracket ] - Drawn OVER the image on the right edge
        if self.show_right_bracket:
            points = [
                width-corner_len, 1,        # Top-right end
                width-2, 1,                 # Top-right corner
                width-2, height-2,          # Bottom-right corner
                width-corner_len, height-2  # Bottom-right end
            ]
            self.right_bracket_id = self.canvas.create_line(
                points,
                width=line_width, fill=color, capstyle="projecting", joinstyle="miter"
            )

    def _on_left_click(self, event):
        """Handle left click - check if on bracket or thumbnail"""
        x = event.x
        width = self.canvas.winfo_width()
        
        # Store drag start position
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.drag_active = False
        
        # Check if clicked on bracket area (left/right 20px)
        if x < 20:  # Left bracket area
            if self.on_bracket_click:
                self.on_bracket_click(self.page_idx, "left", event)
            return
        elif x > width - 20:  # Right bracket area
            if self.on_bracket_click:
                self.on_bracket_click(self.page_idx, "right", event)
            return
        
        # Normal click on thumbnail
        if self.on_click:
            self.on_click(self.page_idx, event)
    
    def _on_drag_motion_internal(self, event):
        """Handle drag motion"""
        # Check if moved enough to start drag (5px threshold)
        dx = abs(event.x - self.drag_start_x)
        dy = abs(event.y - self.drag_start_y)
        
        if not self.drag_active and (dx > 5 or dy > 5):
            # Start drag
            self.drag_active = True
            if self.on_drag_start:
                self.on_drag_start(self.page_idx, event)
        
        if self.drag_active and self.on_drag_motion:
            self.on_drag_motion(self.page_idx, event)
    
    def _on_left_release(self, event):
        """Handle left button release"""
        if self.drag_active and self.on_drag_end:
            self.on_drag_end(self.page_idx, event)
        self.drag_active = False
    
    def _on_right_click(self, event):
        """Handle right click"""
        if self.on_right_click:
            self.on_right_click(self.page_idx, event)
    
    def set_selected(self, selected: bool):
        """Set selection state"""
        self.selected = selected
        self._update_appearance()
    
    def _update_appearance(self):
        """Update visual appearance based on state"""
        # Clear old selection overlay
        if hasattr(self, 'selection_overlay_id') and self.selection_overlay_id:
            self.canvas.delete(self.selection_overlay_id)
            self.selection_overlay_id = None
            
        # Clear old border (if any remains)
        if self.border_id:
            self.canvas.delete(self.border_id)
            self.border_id = None
            
        if self.selected:
            # V1 Style: Blue tint overlay over the image
            # Create a semi-transparent blue image
            w = self.canvas.winfo_width()
            h = self.canvas.winfo_height()
            if w > 1 and h > 1:
                # Create blue overlay with alpha
                # Color: #1F6AA5 is (31, 106, 165)
                # Alpha: 100 (out of 255) for tint
                overlay = Image.new('RGBA', (w, h), (31, 106, 165, 80))
                self.overlay_photo = ImageTk.PhotoImage(overlay)
                
                # Draw overlay on top of image but below brackets
                # We use a tag 'overlay' to manage stacking if needed
                self.selection_overlay_id = self.canvas.create_image(0, 0, image=self.overlay_photo, anchor="nw")
                
                # Ensure brackets are on top
                if self.left_bracket_id:
                    self.canvas.tag_raise(self.left_bracket_id)
                if self.right_bracket_id:
                    self.canvas.tag_raise(self.right_bracket_id)
        else:
            # Normal state - no overlay
            # Optional: Thin grey border for definition? V1 seems to have just the image.
            # Let's add a very subtle border to define the page edge against the background
            w = self.canvas.winfo_width()
            h = self.canvas.winfo_height()
            if w > 1 and h > 1:
                self.border_id = self.canvas.create_rectangle(
                    0, 0, w-1, h-1,
                    outline="#404040", width=1
                )
    
    def update_image(self, image: Image.Image):
        """Update thumbnail image"""
        self.image = image
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.itemconfig(self.image_id, image=self.photo)
