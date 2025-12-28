"""
Theme System - macOS Dark Mode inspired theme
Based on: https://www.behance.net/gallery/38633193/macOS-(OSX)-full-dark-mode-concept

This module centralizes all color definitions for consistent styling across the app.
"""
import customtkinter as ctk


class MacOSDarkTheme:
    """
    macOS-inspired dark mode color palette.
    Elegant, professional, easy on the eyes.
    """
    
    # =========================================================================
    # CORE BACKGROUNDS
    # =========================================================================
    
    # Main window background - deepest layer
    BG_PRIMARY = "#1e1e1e"
    
    # Secondary background - panels, sidebars
    BG_SECONDARY = "#252525"
    
    # Tertiary background - cards, elevated surfaces
    BG_TERTIARY = "#2d2d2d"
    
    # Surface background - inputs, buttons base
    BG_SURFACE = "#353535"
    
    # Hover states
    BG_HOVER = "#3a3a3a"
    
    # Active/pressed states
    BG_ACTIVE = "#404040"
    
    # =========================================================================
    # ACCENT COLORS (macOS Blue)
    # =========================================================================
    
    ACCENT_PRIMARY = "#0a84ff"      # Main accent - buttons, links, selection
    ACCENT_HOVER = "#409cff"        # Lighter on hover
    ACCENT_PRESSED = "#0066cc"      # Darker on press
    ACCENT_SUBTLE = "#0a84ff20"     # Very subtle accent bg (20% opacity)
    
    # =========================================================================
    # TEXT COLORS
    # =========================================================================
    
    TEXT_PRIMARY = "#ffffff"        # Main text - white
    TEXT_SECONDARY = "#a0a0a0"      # Secondary text - muted
    TEXT_TERTIARY = "#6e6e6e"       # Disabled, hints
    TEXT_ACCENT = "#0a84ff"         # Links, interactive text
    
    # =========================================================================
    # BORDERS & SEPARATORS
    # =========================================================================
    
    BORDER_SUBTLE = "#3a3a3a"       # Very subtle borders
    BORDER_DEFAULT = "#4a4a4a"      # Default borders
    BORDER_STRONG = "#5a5a5a"       # Prominent borders
    SEPARATOR = "#333333"           # Dividers between sections
    
    # =========================================================================
    # STATUS COLORS
    # =========================================================================
    
    SUCCESS = "#30d158"             # Green - success states
    WARNING = "#ff9f0a"             # Orange - warnings
    ERROR = "#ff453a"               # Red - errors, destructive
    INFO = "#64d2ff"                # Cyan - information
    
    # =========================================================================
    # SPECIAL STATES
    # =========================================================================
    
    # Selection highlight (for thumbnails, list items)
    SELECTION_BG = "#0a84ff40"      # 40% opacity blue
    SELECTION_BORDER = "#0a84ff"
    
    # Drag and drop
    DROP_TARGET_BG = "#0a84ff20"
    DROP_TARGET_BORDER = "#0a84ff"
    
    # Disabled states
    DISABLED_BG = "#2a2a2a"
    DISABLED_TEXT = "#5a5a5a"
    
    # =========================================================================
    # COMPONENT-SPECIFIC COLORS
    # =========================================================================
    
    # Sidebar
    SIDEBAR_BG = "#202020"
    SIDEBAR_ITEM_BG = "#282828"
    SIDEBAR_ITEM_HOVER = "#333333"
    SIDEBAR_ITEM_ACTIVE = "#0a84ff30"
    
    # Canvas/Grid background
    CANVAS_BG = "#1a1a1a"
    
    # Thumbnail boxes
    THUMB_BG = "#2d2d2d"
    THUMB_BORDER = "#404040"
    THUMB_SELECTED_BORDER = "#0a84ff"
    THUMB_HOVER_BG = "#353535"
    
    # Failed/error boxes
    THUMB_FAILED_BG = "#3a2525"
    THUMB_FAILED_BORDER = "#ff453a50"
    
    # Marked for deletion
    THUMB_MARKED_BG = "#352525"
    
    # Dialogs
    DIALOG_BG = "#282828"
    DIALOG_HEADER_BG = "#2d2d2d"
    
    # Buttons
    BUTTON_PRIMARY_BG = "#0a84ff"
    BUTTON_PRIMARY_HOVER = "#409cff"
    BUTTON_PRIMARY_TEXT = "#ffffff"
    
    BUTTON_SECONDARY_BG = "#353535"
    BUTTON_SECONDARY_HOVER = "#404040"
    BUTTON_SECONDARY_TEXT = "#ffffff"
    BUTTON_SECONDARY_BORDER = "#4a4a4a"
    
    # Input fields
    INPUT_BG = "#1e1e1e"
    INPUT_BORDER = "#4a4a4a"
    INPUT_FOCUS_BORDER = "#0a84ff"
    INPUT_PLACEHOLDER = "#6e6e6e"
    
    # Scrollbars
    SCROLLBAR_BG = "#252525"
    SCROLLBAR_THUMB = "#4a4a4a"
    SCROLLBAR_THUMB_HOVER = "#5a5a5a"
    
    # Progress bars
    PROGRESS_BG = "#353535"
    PROGRESS_FILL = "#0a84ff"
    
    # Tabs
    TAB_BG = "#252525"
    TAB_ACTIVE_BG = "#353535"
    TAB_HOVER_BG = "#303030"
    TAB_BORDER = "#3a3a3a"
    
    # Tooltips
    TOOLTIP_BG = "#3a3a3a"
    TOOLTIP_TEXT = "#ffffff"
    TOOLTIP_BORDER = "#4a4a4a"


class MacOSLightTheme:
    """
    macOS-inspired light mode color palette.
    Clean, bright, professional.
    """
    
    # =========================================================================
    # CORE BACKGROUNDS
    # =========================================================================
    
    BG_PRIMARY = "#f5f5f7"
    BG_SECONDARY = "#ffffff"
    BG_TERTIARY = "#fafafa"
    BG_SURFACE = "#ffffff"
    BG_HOVER = "#f0f0f0"
    BG_ACTIVE = "#e5e5e5"
    
    # =========================================================================
    # ACCENT COLORS
    # =========================================================================
    
    ACCENT_PRIMARY = "#007aff"
    ACCENT_HOVER = "#0066cc"
    ACCENT_PRESSED = "#004499"
    ACCENT_SUBTLE = "#007aff15"
    
    # =========================================================================
    # TEXT COLORS
    # =========================================================================
    
    TEXT_PRIMARY = "#1d1d1f"
    TEXT_SECONDARY = "#6e6e73"
    TEXT_TERTIARY = "#aeaeb2"
    TEXT_ACCENT = "#007aff"
    
    # =========================================================================
    # BORDERS & SEPARATORS
    # =========================================================================
    
    BORDER_SUBTLE = "#e5e5e5"
    BORDER_DEFAULT = "#d2d2d7"
    BORDER_STRONG = "#c7c7cc"
    SEPARATOR = "#e5e5e5"
    
    # =========================================================================
    # STATUS COLORS
    # =========================================================================
    
    SUCCESS = "#34c759"
    WARNING = "#ff9500"
    ERROR = "#ff3b30"
    INFO = "#5ac8fa"
    
    # =========================================================================
    # SPECIAL STATES
    # =========================================================================
    
    SELECTION_BG = "#007aff30"
    SELECTION_BORDER = "#007aff"
    
    DROP_TARGET_BG = "#007aff15"
    DROP_TARGET_BORDER = "#007aff"
    
    DISABLED_BG = "#f5f5f5"
    DISABLED_TEXT = "#c7c7cc"
    
    # =========================================================================
    # COMPONENT-SPECIFIC COLORS
    # =========================================================================
    
    SIDEBAR_BG = "#f5f5f7"
    SIDEBAR_ITEM_BG = "#ffffff"
    SIDEBAR_ITEM_HOVER = "#e8e8ed"
    SIDEBAR_ITEM_ACTIVE = "#007aff20"
    
    CANVAS_BG = "#e8e8ed"
    
    THUMB_BG = "#ffffff"
    THUMB_BORDER = "#d2d2d7"
    THUMB_SELECTED_BORDER = "#007aff"
    THUMB_HOVER_BG = "#f5f5f7"
    
    THUMB_FAILED_BG = "#fff5f5"
    THUMB_FAILED_BORDER = "#ff3b3050"
    
    THUMB_MARKED_BG = "#fff0f0"
    
    DIALOG_BG = "#ffffff"
    DIALOG_HEADER_BG = "#f5f5f7"
    
    BUTTON_PRIMARY_BG = "#007aff"
    BUTTON_PRIMARY_HOVER = "#0066cc"
    BUTTON_PRIMARY_TEXT = "#ffffff"
    
    BUTTON_SECONDARY_BG = "#f5f5f7"
    BUTTON_SECONDARY_HOVER = "#e5e5e5"
    BUTTON_SECONDARY_TEXT = "#1d1d1f"
    BUTTON_SECONDARY_BORDER = "#d2d2d7"
    
    INPUT_BG = "#ffffff"
    INPUT_BORDER = "#d2d2d7"
    INPUT_FOCUS_BORDER = "#007aff"
    INPUT_PLACEHOLDER = "#aeaeb2"
    
    SCROLLBAR_BG = "#f5f5f7"
    SCROLLBAR_THUMB = "#c7c7cc"
    SCROLLBAR_THUMB_HOVER = "#aeaeb2"
    
    PROGRESS_BG = "#e5e5e5"
    PROGRESS_FILL = "#007aff"
    
    TAB_BG = "#f5f5f7"
    TAB_ACTIVE_BG = "#ffffff"
    TAB_HOVER_BG = "#e8e8ed"
    TAB_BORDER = "#d2d2d7"
    
    TOOLTIP_BG = "#1d1d1f"
    TOOLTIP_TEXT = "#ffffff"
    TOOLTIP_BORDER = "#1d1d1f"


def get_theme():
    """Get the current theme based on appearance mode"""
    mode = ctk.get_appearance_mode()
    if mode == "Light":
        return MacOSLightTheme
    return MacOSDarkTheme


def get_color(attr_name: str) -> str:
    """
    Get a color value from the current theme.
    
    Usage:
        bg = get_color("BG_PRIMARY")
        accent = get_color("ACCENT_PRIMARY")
    """
    theme = get_theme()
    return getattr(theme, attr_name, "#ff00ff")  # Magenta fallback for missing colors


# =========================================================================
# CONVENIENCE FUNCTIONS for common color retrievals
# =========================================================================

def bg_primary() -> str:
    return get_color("BG_PRIMARY")

def bg_secondary() -> str:
    return get_color("BG_SECONDARY")

def bg_tertiary() -> str:
    return get_color("BG_TERTIARY")

def bg_surface() -> str:
    return get_color("BG_SURFACE")

def accent() -> str:
    return get_color("ACCENT_PRIMARY")

def text_primary() -> str:
    return get_color("TEXT_PRIMARY")

def text_secondary() -> str:
    return get_color("TEXT_SECONDARY")

def border_default() -> str:
    return get_color("BORDER_DEFAULT")


# =========================================================================
# CUSTOMTKINTER THEME CONFIGURATION
# =========================================================================

def apply_macos_theme():
    """
    Apply macOS-inspired theme settings to CustomTkinter.
    Call this at app startup after setting appearance mode.
    """
    theme = get_theme()
    
    # Note: CustomTkinter has limited theme customization via set_default_color_theme
    # Most styling needs to be done per-widget or via the json theme file
    # This function provides the color values that can be used when creating widgets
    
    return theme


# =========================================================================
# WIDGET STYLE HELPERS
# =========================================================================

def get_button_style(style: str = "primary") -> dict:
    """
    Get button styling kwargs for CTkButton.
    
    Styles: "primary", "secondary", "danger", "success"
    """
    theme = get_theme()
    
    if style == "primary":
        return {
            "fg_color": theme.BUTTON_PRIMARY_BG,
            "hover_color": theme.BUTTON_PRIMARY_HOVER,
            "text_color": theme.BUTTON_PRIMARY_TEXT,
            "border_width": 0,
        }
    elif style == "secondary":
        return {
            "fg_color": theme.BUTTON_SECONDARY_BG,
            "hover_color": theme.BUTTON_SECONDARY_HOVER,
            "text_color": theme.BUTTON_SECONDARY_TEXT,
            "border_width": 1,
            "border_color": theme.BUTTON_SECONDARY_BORDER,
        }
    elif style == "danger":
        return {
            "fg_color": theme.ERROR,
            "hover_color": "#cc3030",
            "text_color": "#ffffff",
            "border_width": 0,
        }
    elif style == "success":
        return {
            "fg_color": theme.SUCCESS,
            "hover_color": "#28a745",
            "text_color": "#ffffff",
            "border_width": 0,
        }
    elif style == "ghost":
        return {
            "fg_color": "transparent",
            "hover_color": theme.BG_HOVER,
            "text_color": theme.TEXT_PRIMARY,
            "border_width": 0,
        }
    
    return {}


def get_input_style() -> dict:
    """Get input field styling kwargs for CTkEntry"""
    theme = get_theme()
    return {
        "fg_color": theme.INPUT_BG,
        "border_color": theme.INPUT_BORDER,
        "text_color": theme.TEXT_PRIMARY,
        "placeholder_text_color": theme.INPUT_PLACEHOLDER,
        "border_width": 1,
    }


def get_frame_style(elevated: bool = False) -> dict:
    """Get frame styling kwargs for CTkFrame"""
    theme = get_theme()
    if elevated:
        return {
            "fg_color": theme.BG_TERTIARY,
            "border_width": 1,
            "border_color": theme.BORDER_SUBTLE,
            "corner_radius": 8,
        }
    return {
        "fg_color": theme.BG_SECONDARY,
        "border_width": 0,
        "corner_radius": 6,
    }


def get_label_style(variant: str = "primary") -> dict:
    """Get label styling kwargs for CTkLabel"""
    theme = get_theme()
    
    if variant == "primary":
        return {"text_color": theme.TEXT_PRIMARY}
    elif variant == "secondary":
        return {"text_color": theme.TEXT_SECONDARY}
    elif variant == "accent":
        return {"text_color": theme.TEXT_ACCENT}
    elif variant == "error":
        return {"text_color": theme.ERROR}
    
    return {"text_color": theme.TEXT_PRIMARY}


# =========================================================================
# MENU ICONS - Segoe Fluent Icons rendered to PhotoImage
# =========================================================================

from PIL import Image, ImageDraw, ImageFont, ImageTk
import tkinter as tk
from typing import Dict, Optional
import sys

# Segoe Fluent Icons character codes (Windows 11)
# Reference: https://learn.microsoft.com/en-us/windows/apps/design/style/segoe-fluent-icons-font
FLUENT_ICONS = {
    "expand": "\uE8A9",       # FullScreen / Expand
    "edit": "\uE70F",         # Edit
    "merge": "\uE71B",        # Link
    "retry": "\uE72C",        # Refresh
    "folder": "\uE8B7",       # OpenFolder
    "file": "\uE8A5",         # OpenFile
    "upload": "\uE898",       # Upload
    "download": "\uE896",     # Download
    "view": "\uE8A1",         # View
    "collapse": "\uE73F",     # CollapseContent
    "select_all": "\uE8B3",   # SelectAll
    "rotate": "\uE7AD",       # Rotate
    "duplicate": "\uE8C8",    # Copy
    "delete": "\uE74D",       # Delete
    "blank": "\uE7C3",        # Page
    "number": "\uE8EF",       # NumberedList
    "cut": "\uE8C6",          # Cut / Scissors
    "save": "\uE74E",         # Save
    "settings": "\uE713",     # Settings
    "check": "\uE73E",        # CheckMark
    "undo": "\uE7A7",         # Undo
    "redo": "\uE7A6",         # Redo
    "mark": "\uE73A",         # Highlight / Mark
    "unmark": "\uE73B",       # Clear selection
    "split": "\uE8A4",        # Split / OpenPane
    "format": "\uE8D2",       # Font / Format
    "position": "\uE81E",     # MapPin / Position
}

# Cache for rendered icons
_icon_cache: Dict[str, "ImageTk.PhotoImage"] = {}
_fluent_font: Optional[ImageFont.FreeTypeFont] = None
_font_available: Optional[bool] = None


def _get_fluent_font(size: int = 16) -> Optional[ImageFont.FreeTypeFont]:
    """Load Segoe Fluent Icons font"""
    global _fluent_font, _font_available
    
    if _font_available is False:
        return None
    
    if _fluent_font is not None and _fluent_font.size == size:
        return _fluent_font
    
    import os
    
    # Windows font paths - Pillow needs full path on Windows
    windows_fonts = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    
    # Try to load the font by file path (Windows) or name (other OS)
    font_paths = [
        os.path.join(windows_fonts, "SegoeIcons.ttf"),      # Segoe Fluent Icons (Win11)
        os.path.join(windows_fonts, "segmdl2.ttf"),         # Segoe MDL2 Assets (Win10)
        "Segoe Fluent Icons",                               # By name fallback
        "Segoe MDL2 Assets",                                # By name fallback
    ]
    
    for font_path in font_paths:
        try:
            _fluent_font = ImageFont.truetype(font_path, size)
            _font_available = True
            return _fluent_font
        except (OSError, IOError):
            continue
    
    _font_available = False
    return None


def get_menu_icon(name: str, size: int = 16, dimmed: bool = False) -> Optional["ImageTk.PhotoImage"]:
    """
    Get a menu icon as PhotoImage.
    
    Args:
        name: Icon name from FLUENT_ICONS
        size: Icon size in pixels
        dimmed: If True, render with reduced opacity (for disabled items)
        
    Returns:
        PhotoImage or None if icon not available
    """
    # Check cache
    cache_key = f"{name}_{size}_{'dim' if dimmed else 'normal'}"
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]
    
    # Get icon character
    char = FLUENT_ICONS.get(name)
    if not char:
        return None
    
    # Get font
    font = _get_fluent_font(size)
    if not font:
        return None
    
    # Get text color based on theme and dimmed state
    theme = get_theme()
    if dimmed:
        text_color = theme.TEXT_TERTIARY  # More muted for disabled items
    else:
        text_color = theme.TEXT_SECONDARY  # Slightly muted for menu icons
    
    # Create image with transparency
    img_size = size + 4  # Padding
    img = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Get text bounding box for centering
    bbox = draw.textbbox((0, 0), char, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # Center the icon
    x = (img_size - text_width) // 2 - bbox[0]
    y = (img_size - text_height) // 2 - bbox[1]
    
    # Draw the icon
    draw.text((x, y), char, font=font, fill=text_color)
    
    # Convert to PhotoImage
    photo = ImageTk.PhotoImage(img)
    
    # Cache it
    _icon_cache[cache_key] = photo
    
    return photo


def clear_icon_cache():
    """Clear the icon cache (call when theme changes)"""
    global _icon_cache
    _icon_cache.clear()


def icons_available() -> bool:
    """Check if Fluent Icons are available on this system"""
    return _get_fluent_font() is not None
