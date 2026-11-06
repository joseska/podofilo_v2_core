"""
Clase ToolTip reutilizable para mostrar tooltips en widgets de CustomTkinter
"""
import tkinter as tk
from src.ui.theme import get_theme


class ToolTip:
    """Clase simple para mostrar tooltips en widgets con retraso.

    Compatible con widgets compuestos de CustomTkinter (CTkButton, etc.).
    CTkButton es un frame con hijos internos (canvas/label); al mover el cursor
    del frame al hijo se genera Leave+Enter falsos. Para evitarlo, usamos un
    flag _mouse_inside y un delay corto en Leave para verificar si el cursor
    realmente salió del bounding box del widget principal.
    """
    def __init__(self, widget, text, delay=700):
        self.widget = widget
        self.text = text
        self.delay = delay  # Retraso en milisegundos antes de mostrar el tooltip
        self.tooltip_window = None
        self.scheduled_show = None  # ID del after() programado
        self._scheduled_leave = None  # ID del after() para verificar Leave real
        self._mouse_inside = False  # Flag para rastrear si el cursor está dentro

        # Bindear en el widget principal y en todos sus hijos internos
        # para que widgets compuestos de CustomTkinter funcionen correctamente.
        self._bind_recursive(self.widget)

    def _bind_recursive(self, widget):
        """Bindear Enter/Leave en el widget y recursivamente en sus hijos."""
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        for child in widget.winfo_children():
            self._bind_recursive(child)

    def _is_cursor_inside(self):
        """Comprobar si el cursor está dentro del bounding box del widget principal."""
        try:
            mx = self.widget.winfo_pointerx()
            my = self.widget.winfo_pointery()
            wx = self.widget.winfo_rootx()
            wy = self.widget.winfo_rooty()
            ww = self.widget.winfo_width()
            wh = self.widget.winfo_height()
            return wx <= mx <= wx + ww and wy <= my <= wy + wh
        except Exception:
            return False

    def _on_enter(self, event=None):
        """Manejar Enter: cancelar cualquier Leave pendiente y programar tooltip."""
        self._mouse_inside = True
        # Cancelar Leave pendiente (era un Leave falso entre hijos del widget compuesto)
        if self._scheduled_leave:
            self.widget.after_cancel(self._scheduled_leave)
            self._scheduled_leave = None
        # Programar tooltip solo si no hay uno ya programado
        if not self.scheduled_show and not self.tooltip_window:
            self.scheduled_show = self.widget.after(self.delay, self.show_tooltip)

    def _on_leave(self, event=None):
        """Manejar Leave: verificar con un pequeño delay si realmente salimos del widget.

        En widgets compuestos, al pasar del frame padre a un hijo interno se genera
        un Leave falso seguido inmediatamente de un Enter en el hijo. El delay de 50ms
        permite que el Enter del hijo cancele este Leave antes de que se ejecute.
        """
        self._mouse_inside = False
        # Cancelar Leave anterior si había uno pendiente
        if self._scheduled_leave:
            self.widget.after_cancel(self._scheduled_leave)
        # Verificar con delay si realmente salimos
        self._scheduled_leave = self.widget.after(50, self._check_leave)

    def _check_leave(self):
        """Verificar tras el delay si el cursor realmente salió del widget.

        Si _mouse_inside es True (hubo un Enter posterior), no hacemos nada.
        Si el cursor sigue dentro del bounding box del widget, tampoco ocultamos.
        Solo ocultamos si realmente salió.
        """
        self._scheduled_leave = None
        if self._mouse_inside:
            return
        if self._is_cursor_inside():
            return
        self.hide_tooltip()
    
    def show_tooltip(self, event=None):
        """Mostrar tooltip"""
        if self.tooltip_window or not self.text:
            return
        
        # Obtener posición del widget
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        widget_top = self.widget.winfo_rooty()
        widget_bottom = widget_top + self.widget.winfo_height()

        # Detectar si el widget está en la mitad inferior de su ventana toplevel.
        # En ese caso (típicamente botones del footer), mostrar el tooltip ENCIMA
        # para evitar que quede oculto detrás de la barra de tareas de Windows.
        try:
            toplevel = self.widget.winfo_toplevel()
            window_top = toplevel.winfo_rooty()
            window_height = toplevel.winfo_height()
            widget_relative_y = widget_top - window_top
            in_bottom_half = widget_relative_y > window_height // 2
        except Exception:
            in_bottom_half = False

        # Posición Y inicial (se ajustará después con la altura real del tooltip si in_bottom_half)
        if in_bottom_half:
            y = widget_top - 30  # Valor provisional, se recalcula abajo con altura real
        else:
            y = widget_bottom + 5  # Debajo del widget
        
        # Crear ventana de tooltip
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        
        # Obtener colores del tema
        theme = get_theme()
        
        label = tk.Label(
            tw,
            text=self.text,
            justify='left',
            background=theme.TOOLTIP_BG,
            foreground=theme.TOOLTIP_TEXT,
            relief='solid',
            borderwidth=1,
            font=("Segoe UI", 9)
        )
        label.pack(ipadx=5, ipady=2)

        # Forzar cálculo del tamaño real del tooltip antes de posicionarlo
        tw.update_idletasks()
        tw_width = tw.winfo_reqwidth()
        tw_height = tw.winfo_reqheight()
        screen_width = self.widget.winfo_screenwidth()

        # Ajustar X para que el tooltip no se salga por la derecha de la pantalla
        if x + tw_width > screen_width:
            x = screen_width - tw_width - 5
        # Tampoco por la izquierda
        if x < 0:
            x = 5

        # Ajustar Y encima del widget usando la altura real del tooltip
        if in_bottom_half:
            y = widget_top - tw_height - 5

        tw.wm_geometry(f"+{x}+{y}")
    
    def hide_tooltip(self, event=None):
        """Ocultar tooltip y cancelar cualquier aparición programada"""
        # Cancelar tooltip programado si existe
        if self.scheduled_show:
            self.widget.after_cancel(self.scheduled_show)
            self.scheduled_show = None
        
        # Destruir tooltip si está visible
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None
