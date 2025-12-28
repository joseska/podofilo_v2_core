import customtkinter as ctk
from tkinter import filedialog, messagebox
from typing import List, Callable
from pathlib import Path
import logging

from src.pdf.structure import Section
from src.ui.theme import get_theme, get_button_style

log = logging.getLogger(__name__)

class SaveDialog(ctk.CTkToplevel):
    """Dialog for saving multiple sections as PDFs"""
    
    def __init__(self, parent, sections: List[Section], initial_dir: str, on_save: Callable):
        super().__init__(parent)
        
        self.sections = sections
        self.on_save = on_save
        self.selected_sections = [] # List of (section, name_var, check_var)
        
        self.title("Guardar como PDF...")
        self.geometry("1000x600")
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._setup_ui(initial_dir)
        self.center_window()
        
        # Bind Enter key to save action
        self.bind("<Return>", lambda e: self._on_save())
        self.btn_save.focus_set()

    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        
        if self.master:
            parent_x = self.master.winfo_x()
            parent_y = self.master.winfo_y()
            parent_width = self.master.winfo_width()
            parent_height = self.master.winfo_height()
            
            x = parent_x + (parent_width // 2) - (width // 2)
            y = parent_y + (parent_height // 2) - (height // 2)
        else:
            x = (self.winfo_screenwidth() // 2) - (width // 2)
            y = (self.winfo_screenheight() // 2) - (height // 2)
            
        self.geometry(f'{width}x{height}+{x}+{y}')

    def _setup_ui(self, initial_dir):
        # 1. Directory selection
        dir_frame = ctk.CTkFrame(self)
        dir_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(dir_frame, text="Carpeta donde se guardarán los documentos", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=5)
        
        self.dir_var = ctk.StringVar(value=initial_dir)
        self.entry_dir = ctk.CTkEntry(dir_frame, textvariable=self.dir_var, font=("Segoe UI", 12), height=26, corner_radius=1)
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
        
        ctk.CTkLabel(header_frame, text="Nombre del documento", width=400, anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left", padx=30)
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
        
        # Name Entry
        name_var = ctk.StringVar(value=section.title)
        entry = ctk.CTkEntry(row, font=("Segoe UI", 10), height=26, corner_radius=1)
        entry.configure(textvariable=name_var)
        entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # Page Count
        lbl_count = ctk.CTkLabel(row, text=str(section.page_count), width=50, font=("Segoe UI", 10))
        lbl_count.pack(side="right", padx=5)
        
        self.selected_sections.append({
            "section": section,
            "name_var": name_var,
            "check_var": check_var
        })
        
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
