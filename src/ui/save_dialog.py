import customtkinter as ctk
from tkinter import filedialog, messagebox
import tkinter as tk
from typing import List, Callable, Tuple, Optional
from pathlib import Path
import logging
from PIL import Image

from src.pdf.structure import Section
from src.ui.theme import get_theme, get_button_style
from src.ui.tooltip import ToolTip

log = logging.getLogger(__name__)

class SaveDialog(ctk.CTkToplevel):
    """Dialog for saving multiple sections as PDFs"""
    
    def __init__(self, parent, sections: List[Section], initial_dir: str, on_save: Callable, 
                 split_pages: int = 6, split_mb: int = 5):
        super().__init__(parent)
        
        self.sections = sections
        self.on_save = on_save
        self.selected_sections = [] # List of (section, name_var, check_var)
        self.split_pages = split_pages  # Valor para dividir por páginas (ej: 6)
        self.split_mb = split_mb  # Valor para dividir por MB (ej: 5)
        
        self.title("Guardar como PDF...")
        # Ajustamos tamaño inicial según monitor para evitar diálogos recortados en resoluciones bajas.
        self._apply_adaptive_initial_geometry()
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._setup_ui(initial_dir)
        self.center_window()
        
        # Bind Enter key to save action
        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.btn_save.focus_set()

    def _apply_adaptive_initial_geometry(self):
        """Define geometría inicial adaptable al monitor actual."""
        _, _, work_width, work_height = self._get_monitor_work_area()

        # Se limita a un porcentaje del monitor para no ocupar toda la pantalla en equipos pequeños.
        max_width = max(320, int(work_width * 0.95))
        max_height = max(260, int(work_height * 0.90))

        # Tope absoluto para mantener una huella consistente incluso en monitores grandes.
        width = min(900, max_width)
        height = min(580, max_height)

        # Mínimos dinámicos: mejoran usabilidad sin forzar tamaños que no caben.
        min_width = min(760, max_width)
        min_height = min(420, max_height)

        self.geometry(f"{width}x{height}")
        self.minsize(min_width, min_height)

    def _get_monitor_work_area(self) -> Tuple[int, int, int, int]:
        """Obtiene el área de trabajo del monitor objetivo (x, y, ancho, alto)."""
        fallback_area = (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())

        # En Windows intentamos usar la API nativa para detectar el monitor real de la ventana padre.
        try:
            if self.tk.call("tk", "windowingsystem") == "win32":
                win_area = self._get_windows_monitor_work_area()
                if win_area:
                    return win_area
        except Exception as exc:
            log.debug("No se pudo obtener área de monitor con API Win32: %s", exc)

        # Fallback multiplataforma: área virtual reportada por Tk.
        try:
            self.update_idletasks()
            vroot_width = self.winfo_vrootwidth()
            vroot_height = self.winfo_vrootheight()
            if vroot_width > 0 and vroot_height > 0:
                return (self.winfo_vrootx(), self.winfo_vrooty(), vroot_width, vroot_height)
        except Exception:
            pass

        return fallback_area

    def _get_windows_monitor_work_area(self) -> Optional[Tuple[int, int, int, int]]:
        """Obtiene el área útil del monitor (sin barra de tareas) usando Win32."""
        import ctypes
        from ctypes import wintypes

        target_widget = self.master if self.master else self
        target_widget.update_idletasks()
        hwnd = target_widget.winfo_id()
        if not hwnd:
            return None

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        monitor_default_to_nearest = 2
        user32 = ctypes.windll.user32
        h_monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), monitor_default_to_nearest)
        if not h_monitor:
            return None

        monitor_info = MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(h_monitor, ctypes.byref(monitor_info)):
            return None

        work_area = monitor_info.rcWork
        return (
            work_area.left,
            work_area.top,
            work_area.right - work_area.left,
            work_area.bottom - work_area.top,
        )

    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        work_x, work_y, work_width, work_height = self._get_monitor_work_area()
        
        if self.master:
            # Centramos respecto a la ventana principal para mantener contexto visual.
            self.master.update_idletasks()
            parent_x = self.master.winfo_rootx()
            parent_y = self.master.winfo_rooty()
            parent_width = self.master.winfo_width()
            parent_height = self.master.winfo_height()
            
            x = parent_x + (parent_width // 2) - (width // 2)
            y = parent_y + (parent_height // 2) - (height // 2)
        else:
            x = work_x + (work_width // 2) - (width // 2)
            y = work_y + (work_height // 2) - (height // 2)

        # Acotamos la posición para garantizar que el diálogo siempre quede completamente visible.
        max_x = work_x + max(0, work_width - width)
        max_y = work_y + max(0, work_height - height)
        x = min(max(x, work_x), max_x)
        y = min(max(y, work_y), max_y)
            
        self.geometry(f'{width}x{height}+{x}+{y}')

    def _setup_ui(self, initial_dir):
        # 1. Directory selection
        dir_frame = ctk.CTkFrame(self)
        dir_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(dir_frame, text="Carpeta donde se guardarán los documentos", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=5)
        
        self.dir_var = ctk.StringVar(value=initial_dir)
        self.entry_dir = ctk.CTkEntry(dir_frame, textvariable=self.dir_var, font=("Segoe UI", 13), height=26, corner_radius=1)
        self.entry_dir.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        
        btn_browse = ctk.CTkButton(dir_frame, text="Browse", width=70, height=26, font=("Segoe UI", 11), command=self._browse_dir)
        btn_browse.pack(side="right", padx=5)
        
        # 2. Sections List Header
        header_frame = ctk.CTkFrame(self, height=30)
        header_frame.pack(fill="x", padx=10)
        
        # Columns: Select All, Name, Pages
        self.all_var = ctk.BooleanVar(value=True)
        self.chk_all = ctk.CTkCheckBox(
            header_frame,
            text="",
            variable=self.all_var,
            width=20,
            border_width=2,
            corner_radius=1,
            checkbox_width=16,
            checkbox_height=16,
            command=self._on_toggle_all
        )
        self.chk_all.pack(side="left", padx=(10, 5))
        
        # Label "Nombre del documento"
        label_nombre = ctk.CTkLabel(header_frame, text="Nombre del documento", anchor="w", font=("Segoe UI", 12, "bold"))
        label_nombre.pack(side="left", padx=5)
        
        # Botón de renumeración automática con icono PNG (justo después del texto)
        # Cargar iconos según el tema (claro/oscuro)
        icon_dir = Path(__file__).parent.parent.parent / "resources" / "icons"
        icon_light = ctk.CTkImage(
            light_image=Image.open(icon_dir / "autonumero_black.png"),
            dark_image=Image.open(icon_dir / "autonumero_white.png"),
            size=(16, 16)
        )
        btn_renumber = ctk.CTkButton(
            header_frame,
            text="",
            image=icon_light,
            width=24,
            height=24,
            command=self._auto_renumber_files,
            fg_color="transparent",
            hover_color=("gray85", "gray25"),
            corner_radius=4
        )
        btn_renumber.pack(side="left", padx=(2, 0))
        ToolTip(btn_renumber, "Autonumerar archivos (1, 2, 3...)")
        
        ctk.CTkLabel(header_frame, text="Págs", width=50, font=("Segoe UI", 10, "bold")).pack(side="right", padx=20)
        
        # 3. Sections List (Scrollable)
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Populate items
        for section in self.sections:
            self._add_item(section)
        
        # Sincronizar checkbox maestro con el estado inicial
        self._update_save_button()
        
        # 4. Create combined file option
        combined_frame = ctk.CTkFrame(self)
        combined_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        self.combined_var = ctk.BooleanVar(value=False)
        self.chk_combined = ctk.CTkCheckBox(
            combined_frame,
            text="Unificar PDFs",
            variable=self.combined_var,
            command=self._on_combined_toggle,
            font=("Segoe UI", 10),
            border_width=2,
            corner_radius=1,
            checkbox_width=16,
            checkbox_height=16
        )
        self.chk_combined.pack(side="left", padx=5)
        
        # Combined filename input
        self.combined_name_var = ctk.StringVar(value="")
        self.entry_combined = ctk.CTkEntry(
            combined_frame, 
            textvariable=self.combined_name_var,
            font=("Segoe UI", 10),
            width=300,
            height=26,
            corner_radius=1,
            placeholder_text="Nombre del archivo unificado",
            state="disabled"
        )
        self.entry_combined.pack(side="left", padx=(10, 5))
        
        # Bind directory change to update combined name suggestion
        self.dir_var.trace_add("write", self._update_combined_name_suggestion)
            
        # 5. Bottom buttons
        btn_frame = ctk.CTkFrame(self, height=50, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        self.btn_save = ctk.CTkButton(
            btn_frame, 
            text=f"Guardar {len(self.sections)} PDF", 
            command=self._on_save,
            **get_button_style("primary")
        )
        self.btn_save.pack(side="right", padx=5)
        
        btn_cancel = ctk.CTkButton(
            btn_frame, 
            text="Cancelar", 
            command=self.destroy,
            **get_button_style("secondary")
        )
        btn_cancel.pack(side="right", padx=5)
        
    def _add_item(self, section: Section):
        row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        
        # Checkbox
        check_var = ctk.BooleanVar(value=True)
        chk = ctk.CTkCheckBox(
            row, 
            text="", 
            variable=check_var, 
            width=20,
            border_width=2,
            corner_radius=1,
            checkbox_width=16,
            checkbox_height=16,
            command=self._update_save_button
        )
        chk.pack(side="left", padx=5)
        
        # Name Entry (reducido ligeramente para hacer espacio a los iconos)
        name_var = ctk.StringVar(value=section.title)
        entry = ctk.CTkEntry(row, font=("Segoe UI", 11), height=26, corner_radius=1)
        entry.configure(textvariable=name_var)
        entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # Cargar iconos para los botones de split
        icon_dir = Path(__file__).parent.parent.parent / "resources" / "icons"
        
        # Icono para dividir por páginas
        icon_pages = ctk.CTkImage(
            light_image=Image.open(icon_dir / "dividir_pagina_black.png"),
            dark_image=Image.open(icon_dir / "dividir_pagina_white.png"),
            size=(20, 20)
        )
        
        # Icono para dividir por tamaño
        icon_size = ctk.CTkImage(
            light_image=Image.open(icon_dir / "dividir_tamano_black.png"),
            dark_image=Image.open(icon_dir / "dividir_tamano_white.png"),
            size=(20, 20)
        )
        
        # Page Count (se coloca primero en side="right" para que aparezca al final)
        lbl_count = ctk.CTkLabel(row, text=str(section.page_count), width=50, font=("Segoe UI", 10))
        lbl_count.pack(side="right", padx=5)
        
        # Botón para añadir sufijo /Xp (dividir por páginas) - con icono
        btn_pages = ctk.CTkButton(
            row,
            text="",
            image=icon_pages,
            width=24,
            height=22,
            fg_color="transparent",
            hover_color=("gray85", "gray25"),
            corner_radius=4,
            command=lambda nv=name_var: self._add_pages_suffix(nv)
        )
        btn_pages.pack(side="right", padx=(0, 0))  # Menos padding entre iconos
        ToolTip(btn_pages, f"Dividir por páginas (/{self.split_pages}p)")
        
        # Botón para añadir sufijo /XM (dividir por MB) - con icono
        btn_mb = ctk.CTkButton(
            row,
            text="",
            image=icon_size,
            width=24,
            height=22,
            fg_color="transparent",
            hover_color=("gray85", "gray25"),
            corner_radius=4,
            command=lambda nv=name_var: self._add_mb_suffix(nv)
        )
        btn_mb.pack(side="right", padx=(0, 0))  # Menos padding entre iconos
        ToolTip(btn_mb, f"Dividir por tamaño (/{self.split_mb}M)")
        
        self.selected_sections.append({
            "section": section,
            "name_var": name_var,
            "check_var": check_var
        })
        
        # Sincronizar cambios de nombre con la sección original
        # Esto permite que los modificadores añadidos desde el diálogo se reflejen en section.title
        name_var.trace_add("write", lambda *args, s=section, nv=name_var: self._sync_section_title(s, nv))
        
    def _add_pages_suffix(self, name_var: ctk.StringVar):
        """Añadir sufijo /Xp al nombre del archivo (dividir por páginas)"""
        import re
        current_name = name_var.get()
        # Eliminar sufijo previo si existe (patrón: /número seguido de p, M, K, o B)
        base_name = re.sub(r'/\d+[pPbBmMkK]$', '', current_name)
        # Añadir nuevo sufijo
        new_name = f"{base_name}/{self.split_pages}p"
        name_var.set(new_name)
    
    def _add_mb_suffix(self, name_var: ctk.StringVar):
        """Añadir sufijo /XM al nombre del archivo (dividir por MB)"""
        import re
        current_name = name_var.get()
        # Eliminar sufijo previo si existe (patrón: /número seguido de p, M, K, o B)
        base_name = re.sub(r'/\d+[pPbBmMkK]$', '', current_name)
        # Añadir nuevo sufijo
        new_name = f"{base_name}/{self.split_mb}M"
        name_var.set(new_name)
    
    def _browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get())
        if d:
            self.dir_var.set(d)
    
    def _on_combined_toggle(self):
        """Handle combined checkbox toggle"""
        if self.combined_var.get():
            self.entry_combined.configure(state="normal")
            # Auto-fill with last folder name from path
            self._update_combined_name_suggestion()
        else:
            self.entry_combined.configure(state="disabled")
    
    def _update_combined_name_suggestion(self, *args):
        """Update combined filename suggestion based on directory path"""
        if not self.combined_var.get():
            return
        
        dir_path = self.dir_var.get()
        if dir_path:
            # Get the last folder name from the path
            folder_name = Path(dir_path).name
            if folder_name:
                self.combined_name_var.set(folder_name)
            
    def _on_toggle_all(self):
        """Selecciona/deselecciona todas las secciones."""
        target_state = self.all_var.get()
        for item in self.selected_sections:
            item["check_var"].set(target_state)
        self._update_save_button(update_master=False)
        
    def _update_save_button(self, update_master=True):
        count = sum(1 for item in self.selected_sections if item["check_var"].get())
        if hasattr(self, 'btn_save'):
            self.btn_save.configure(text=f"Guardar {count} PDF")
        
        if update_master and self.selected_sections:
            all_checked = (count == len(self.selected_sections))
            self.all_var.set(all_checked)
        
    def _on_save(self):
        target_dir = self.dir_var.get()
        if not target_dir:
            messagebox.showerror("Error", "Seleccione una carpeta de destino")
            return
            
        to_save = []
        for item in self.selected_sections:
            if item["check_var"].get():
                to_save.append({
                    "section": item["section"],
                    "filename": item["name_var"].get()
                })
        
        if not to_save:
            return
        
        # Check if combined file should be created
        combined_filename = None
        if self.combined_var.get():
            combined_name = self.combined_name_var.get().strip()
            if not combined_name:
                messagebox.showerror("Error", "Ingrese un nombre para el archivo completo")
                return
            combined_filename = combined_name
            
        self.on_save(target_dir, to_save, combined_filename)
        self.destroy()
    
    def _sync_section_title(self, section: Section, name_var: ctk.StringVar):
        """Sincroniza el título de la sección con el valor del name_var.
        
        Esto permite que los cambios hechos en el diálogo (modificadores, autonumeración)
        se reflejen directamente en la sección original, evitando inconsistencias al guardar.
        """
        new_title = name_var.get()
        if section.title != new_title:
            section.title = new_title
            # También parsear y actualizar split_config si hay modificador
            import re
            match = re.search(r'/(\d+)([pPbBmMkK])$', new_title)
            if match:
                val = int(match.group(1))
                unit = match.group(2).lower()
                if unit == 'p':
                    section.split_config = (val, 'p')
                elif unit == 'm':
                    section.split_config = (val * 1024 * 1024, 'b')
                elif unit == 'k':
                    section.split_config = (val * 1024, 'b')
                elif unit == 'b':
                    section.split_config = (val, 'b')
            else:
                # Sin modificador, limpiar split_config
                section.split_config = None
    
    def _auto_renumber_files(self):
        """Renumera automáticamente todos los archivos añadiendo prefijo numérico (1, 2, 3...)"""
        for idx, item in enumerate(self.selected_sections, start=1):
            current_name = item["name_var"].get()
            # Eliminar numeración previa si existe (patrón: "N " al inicio)
            import re
            cleaned_name = re.sub(r'^\d+\s+', '', current_name)
            # Añadir nueva numeración
            new_name = f"{idx} {cleaned_name}"
            item["name_var"].set(new_name)
