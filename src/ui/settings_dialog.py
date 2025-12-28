"""
Settings Dialog - Ventana de configuración de la aplicación
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from typing import List, Callable
from pathlib import Path
import json

from src.ui.theme import get_theme, get_button_style

class SettingsDialog(ctk.CTkToplevel):
    """Dialog for application settings"""
    
    def __init__(self, parent, config_manager, on_save: Callable = None, ove_enabled: bool = True):
        super().__init__(parent)
        
        self.config_manager = config_manager
        self.on_save = on_save
        self.ove_enabled = ove_enabled
        
        self.title("Configuración de Podofilo")
        self.geometry("800x680")
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._setup_ui()
        self.center_window()
        
    def center_window(self):
        self.update_idletasks()
        
        # Get dialog dimensions
        width = self.winfo_width()
        height = self.winfo_height()
        
        # Fallback if not realized
        if width <= 1 or height <= 1:
            width = 800
            height = 680
        
        # Get parent dimensions and position
        if self.master:
            parent_x = self.master.winfo_x()
            parent_y = self.master.winfo_y()
            parent_width = self.master.winfo_width()
            parent_height = self.master.winfo_height()
            
            x = parent_x + (parent_width // 2) - (width // 2)
            y = parent_y + (parent_height // 2) - (height // 2)
        else:
            # Fallback to screen center
            x = (self.winfo_screenwidth() // 2) - (width // 2)
            y = (self.winfo_screenheight() // 2) - (height // 2)
            
        self.geometry(f'{width}x{height}+{x}+{y}')
        
    def _setup_ui(self):
        # Main container with tabs
        self.tabview = ctk.CTkTabview(self, width=780, height=500)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Create tabs
        self.tab_general = self.tabview.add("General")
        self.tab_watcher = self.tabview.add("Vigilancia")
        self.tab_sections = self.tabview.add("Nombres de Secciones")
        self.tab_advanced = self.tabview.add("Avanzado")
        
        self._setup_general_tab()
        self._setup_watcher_tab()
        self._setup_sections_tab()
        self._setup_advanced_tab()
        
        # Bottom buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkButton(
            btn_frame,
            text="Guardar",
            command=self._save_settings,
            width=120,
            **get_button_style("primary")
        ).pack(side="right", padx=5)
        
        ctk.CTkButton(
            btn_frame,
            text="Cancelar",
            command=self.destroy,
            width=120,
            **get_button_style("secondary")
        ).pack(side="right", padx=5)
        
    def _setup_general_tab(self):
        """Setup General settings tab"""
        # Nombre predeterminado
        frame = ctk.CTkFrame(self.tab_general, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(
            frame,
            text="Nombre predeterminado para nuevas secciones:",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 10))
        
        self.default_name_entry = ctk.CTkEntry(
            frame,
            font=("Segoe UI", 11),
            corner_radius=1,
            placeholder_text="Ej: resultado"
        )
        self.default_name_entry.pack(fill="x", pady=5)
        self.default_name_entry.insert(0, self.config_manager.get_default_base_name())
        
        # Split defaults
        split_frame = ctk.CTkFrame(self.tab_general, fg_color="transparent")
        split_frame.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(
            split_frame,
            text="Valores predeterminados para división:",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 10))
        
        # Pages
        pages_frame = ctk.CTkFrame(split_frame, fg_color="transparent")
        pages_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(
            pages_frame,
            text="Páginas por archivo:",
            font=("Segoe UI", 11)
        ).pack(side="left", padx=(0, 10))
        
        self.split_pages_entry = ctk.CTkEntry(
            pages_frame,
            font=("Segoe UI", 11),
            width=100,
            corner_radius=1
        )
        self.split_pages_entry.pack(side="left")
        self.split_pages_entry.insert(0, str(self.config_manager.get_last_split_pages()))
        
        # Size
        size_frame = ctk.CTkFrame(split_frame, fg_color="transparent")
        size_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(
            size_frame,
            text="Tamaño máximo (MB):",
            font=("Segoe UI", 11)
        ).pack(side="left", padx=(0, 10))
        
        self.split_size_entry = ctk.CTkEntry(
            size_frame,
            font=("Segoe UI", 11),
            width=100,
            corner_radius=1
        )
        self.split_size_entry.pack(side="left")
        self.split_size_entry.insert(0, str(self.config_manager.get_last_split_size_mb()))

        # OVE Settings
        if self.ove_enabled:
            ove_frame = ctk.CTkFrame(self.tab_general, fg_color="transparent")
            ove_frame.pack(fill="x", padx=20, pady=20)

            ctk.CTkLabel(
                ove_frame,
                text="Opciones de OVE:",
                font=("Segoe UI", 12, "bold")
            ).pack(anchor="w", pady=(0, 10))

            self.ove_show_browser_var = ctk.BooleanVar(value=self.config_manager.get_ove_show_browser())
            ctk.CTkCheckBox(
                ove_frame,
                text="Modo Debug: Mostrar navegador OVE (no oculto)",
                variable=self.ove_show_browser_var,
                font=("Segoe UI", 11),
                border_width=2,
                corner_radius=1
            ).pack(anchor="w", pady=5)

            self.ove_auto_connect_var = ctk.BooleanVar(value=self.config_manager.get_ove_auto_connect())
            ctk.CTkCheckBox(
                ove_frame,
                text="NO conectar automáticamente al OVE (retraso de 1s)",
                variable=self.ove_auto_connect_var,
                font=("Segoe UI", 11),
                border_width=2,
                corner_radius=1
            ).pack(anchor="w")

        # Appearance Settings
        appearance_frame = ctk.CTkFrame(self.tab_general, fg_color="transparent")
        appearance_frame.pack(fill="x", padx=20, pady=20)

        ctk.CTkLabel(
            appearance_frame,
            text="Apariencia:",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 10))

        theme_row = ctk.CTkFrame(appearance_frame, fg_color="transparent")
        theme_row.pack(fill="x", pady=5)

        ctk.CTkLabel(
            theme_row,
            text="Tema de la interfaz:",
            font=("Segoe UI", 11)
        ).pack(side="left", padx=(0, 10))

        # Map internal values to display names
        self._appearance_options = {
            "Oscuro": "dark",
            "Claro": "light",
            "Sistema": "system"
        }
        self._appearance_reverse = {v: k for k, v in self._appearance_options.items()}

        current_mode = self.config_manager.get_appearance_mode()
        current_display = self._appearance_reverse.get(current_mode, "Oscuro")

        self.appearance_var = ctk.StringVar(value=current_display)
        self.appearance_menu = ctk.CTkOptionMenu(
            theme_row,
            values=list(self._appearance_options.keys()),
            variable=self.appearance_var,
            font=("Segoe UI", 11),
            width=150
            # Removed command to prevent immediate crash
        )
        self.appearance_menu.pack(side="left")

        self.appearance_note = ctk.CTkLabel(
            appearance_frame,
            text="💡 El cambio de tema requiere reiniciar la aplicación",
            font=("Segoe UI", 10),
            text_color="gray"
        )
        self.appearance_note.pack(anchor="w", pady=(5, 0))
        
    def _setup_watcher_tab(self):
        """Setup Watcher settings tab"""
        # Description
        desc_frame = ctk.CTkFrame(self.tab_watcher, fg_color="transparent")
        desc_frame.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(
            desc_frame,
            text="Carpetas vigiladas:",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 5))
        
        ctk.CTkLabel(
            desc_frame,
            text="Podofilo abrirá automáticamente cualquier PDF que aparezca en estas carpetas.",
            font=("Segoe UI", 11),
            text_color="gray"
        ).pack(anchor="w")

        # Auto-delete Checkbox
        self.watch_auto_delete_var = ctk.BooleanVar(value=self.config_manager.get_watch_auto_delete())
        ctk.CTkCheckBox(
            desc_frame,
            text="Borrar archivos automáticamente tras importarlos (Recomendado para impresoras virtuales)",
            variable=self.watch_auto_delete_var,
            font=("Segoe UI", 11),
            border_width=2,
            corner_radius=1
        ).pack(anchor="w", pady=(10, 0))

        # Optimize Import Checkbox
        self.watch_optimize_import_var = ctk.BooleanVar(value=self.config_manager.get_watch_optimize_import())
        ctk.CTkCheckBox(
            desc_frame,
            text="Optimizar PDF al importar (reduce tamaño manteniendo calidad, elimina basura)",
            variable=self.watch_optimize_import_var,
            font=("Segoe UI", 11),
            border_width=2,
            corner_radius=1
        ).pack(anchor="w", pady=(5, 0))

        # Buttons Toolbar
        toolbar = ctk.CTkFrame(self.tab_watcher, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(0, 5))

        ctk.CTkButton(
            toolbar,
            text="➕ Añadir Carpeta",
            width=120,
            command=self._add_watched_folder
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            toolbar,
            text="❌ Eliminar",
            width=100,
            command=self._remove_watched_folder,
            fg_color="#C9302C",
            hover_color="#A9201C"
        ).pack(side="left", padx=2)

        # Folder List
        list_frame = ctk.CTkFrame(self.tab_watcher)
        list_frame.pack(fill="both", expand=True, padx=20, pady=5)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self.folders_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            font=("Segoe UI", 11),
            bd=0,
            highlightthickness=0,
            activestyle="none",
            yscrollcommand=scrollbar.set
        )
        self.folders_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.folders_listbox.yview)

        # Populate list
        self.watched_folders = list(self.config_manager.get_watched_folders())
        for folder in self.watched_folders:
            self.folders_listbox.insert(tk.END, folder)
            
    def _add_watched_folder(self):
        """Add folder via dialog"""
        folder = tk.filedialog.askdirectory(parent=self, title="Seleccionar carpeta para vigilar")
        if folder:
            # Normalize path
            folder = str(Path(folder).absolute())
            if folder not in self.watched_folders:
                self.watched_folders.append(folder)
                self.folders_listbox.insert(tk.END, folder)
            else:
                messagebox.showinfo("Información", "Esta carpeta ya está en la lista.")
    
    def _remove_watched_folder(self):
        """Remove selected folder"""
        sel = self.folders_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.watched_folders.pop(idx)
        self.folders_listbox.delete(idx)        
    def _setup_sections_tab(self):
        """Setup Section Names tab"""
        # Info label
        ctk.CTkLabel(
            self.tab_sections,
            text="Lista de nombres predefinidos para secciones (aparecen en el menú contextual):",
            font=("Segoe UI", 11),
            wraplength=750
        ).pack(anchor="w", padx=20, pady=(20, 10))
        
        # Toolbar
        toolbar = ctk.CTkFrame(self.tab_sections, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(0, 5))
        
        ctk.CTkButton(
            toolbar,
            text="➕ Añadir",
            width=100,
            command=self._add_section_name
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            toolbar,
            text="✏️ Editar",
            width=100,
            command=self._edit_section_name
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            toolbar,
            text="❌ Eliminar",
            width=100,
            command=self._remove_section_name,
            fg_color="#C9302C",
            hover_color="#A9201C"
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            toolbar,
            text="⬆️",
            width=50,
            command=self._move_up
        ).pack(side="right", padx=2)
        
        ctk.CTkButton(
            toolbar,
            text="⬇️",
            width=50,
            command=self._move_down
        ).pack(side="right", padx=2)
        
        # List frame
        list_frame = ctk.CTkFrame(self.tab_sections)
        list_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        # Scrollbar
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        # Listbox
        self.sections_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            font=("Segoe UI", 11),
            bd=0,
            highlightthickness=0,
            activestyle="none",
            yscrollcommand=scrollbar.set
        )
        self.sections_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.sections_listbox.yview)
        
        # Populate list
        self.section_names = list(self.config_manager.get_section_names())
        for name in self.section_names:
            self.sections_listbox.insert(tk.END, name)
            
        # Double click to edit
        self.sections_listbox.bind("<Double-Button-1>", lambda e: self._edit_section_name())
        
    def _setup_advanced_tab(self):
        """Setup Advanced settings tab"""
        # Config file location
        frame = ctk.CTkFrame(self.tab_advanced, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(
            frame,
            text="Ubicación del archivo de configuración:",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 10))
        
        config_path = str(self.config_manager.config_file)
        
        path_frame = ctk.CTkFrame(frame, fg_color="transparent")
        path_frame.pack(fill="x")
        
        path_entry = ctk.CTkEntry(
            path_frame,
            font=("Segoe UI", 10),
            corner_radius=1
        )
        path_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        path_entry.insert(0, config_path)
        path_entry.configure(state="readonly")
        
        ctk.CTkButton(
            path_frame,
            text="📂 Abrir carpeta",
            width=120,
            command=self._open_config_folder
        ).pack(side="right")
        
        # View raw config
        view_frame = ctk.CTkFrame(self.tab_advanced, fg_color="transparent")
        view_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(
            view_frame,
            text="Contenido del archivo de configuración:",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 10))
        
        # Text widget for config
        text_frame = ctk.CTkFrame(view_frame)
        text_frame.pack(fill="both", expand=True)
        
        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        
        # Adaptive colors for config preview using theme
        theme = get_theme()
        config_bg = theme.INPUT_BG
        config_fg = theme.TEXT_PRIMARY
        self.config_text = tk.Text(
            text_frame,
            wrap="word",
            font=("Consolas", 10),
            bg=config_bg,
            fg=config_fg,
            bd=0,
            highlightthickness=0,
            yscrollcommand=scrollbar.set
        )
        self.config_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.config_text.yview)
        
        # Load config content
        self._load_config_preview()
        
        # Reload button
        # ctk.CTkButton(
        #     view_frame,
        #     text="🔄 Recargar vista previa",
        #     command=self._load_config_preview,
        #     width=150
        # ).pack(pady=(10, 0))
        
    def _load_config_preview(self):
        """Load and display config file content"""
        try:
            with open(self.config_manager.config_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self.config_text.configure(state="normal")
            self.config_text.delete("1.0", "end")
            self.config_text.insert("1.0", content)
            self.config_text.configure(state="disabled")
        except Exception as e:
            self.config_text.configure(state="normal")
            self.config_text.delete("1.0", "end")
            self.config_text.insert("1.0", f"Error al cargar configuración:\n{e}")
            self.config_text.configure(state="disabled")
    
    def _open_config_folder(self):
        """Open config folder in file explorer"""
        import subprocess
        import platform
        
        folder = self.config_manager.config_dir
        
        try:
            if platform.system() == "Windows":
                subprocess.run(["explorer", str(folder)])
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(folder)])
            else:  # Linux
                subprocess.run(["xdg-open", str(folder)])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")
    
    def _add_section_name(self):
        """Add new section name"""
        from src.ui.dialogs import CenteredInputDialog
        dialog = CenteredInputDialog(self, "Agregar Nombre", "Nombre de sección:")
        name = dialog.get_input()
        if name:
            self.section_names.append(name)
            self.sections_listbox.insert(tk.END, name)
            self.sections_listbox.see(tk.END)
            
    def _edit_section_name(self):
        """Edit selected section name"""
        from src.ui.dialogs import CenteredInputDialog
        sel = self.sections_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        current = self.section_names[idx]
        
        dialog = CenteredInputDialog(self, "Editar Nombre", "Nombre de sección:", initial_value=current)
        new_name = dialog.get_input()
        if new_name:
            self.section_names[idx] = new_name
            self.sections_listbox.delete(idx)
            self.sections_listbox.insert(idx, new_name)
            self.sections_listbox.selection_set(idx)
            
    def _remove_section_name(self):
        """Remove selected section name"""
        sel = self.sections_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.section_names.pop(idx)
        self.sections_listbox.delete(idx)
        
        # Select next if available
        if idx < self.sections_listbox.size():
            self.sections_listbox.selection_set(idx)
        elif self.sections_listbox.size() > 0:
            self.sections_listbox.selection_set(self.sections_listbox.size() - 1)
            
    def _move_up(self):
        """Move selected item up"""
        sel = self.sections_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx > 0:
            # Swap in list
            self.section_names[idx], self.section_names[idx-1] = self.section_names[idx-1], self.section_names[idx]
            
            # Swap in listbox
            text = self.sections_listbox.get(idx)
            self.sections_listbox.delete(idx)
            self.sections_listbox.insert(idx-1, text)
            self.sections_listbox.selection_set(idx-1)
            self.sections_listbox.see(idx-1)
            
    def _move_down(self):
        """Move selected item down"""
        sel = self.sections_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self.section_names) - 1:
            # Swap in list
            self.section_names[idx], self.section_names[idx+1] = self.section_names[idx+1], self.section_names[idx]
            
            # Swap in listbox
            text = self.sections_listbox.get(idx)
            self.sections_listbox.delete(idx)
            self.sections_listbox.insert(idx+1, text)
            self.sections_listbox.selection_set(idx+1)
            self.sections_listbox.see(idx+1)

    # Removed _on_appearance_change method as it's no longer used
    
    def _save_settings(self):
        """Save all settings"""
        try:
            # Validate inputs
            default_name = self.default_name_entry.get().strip()
            if not default_name:
                messagebox.showerror("Error", "El nombre predeterminado no puede estar vacío")
                return
            
            try:
                split_pages = int(self.split_pages_entry.get())
                if split_pages <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Error", "Las páginas por archivo deben ser un número entero positivo")
                return
            
            try:
                split_size = int(self.split_size_entry.get())
                if split_size <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Error", "El tamaño máximo debe ser un número entero positivo")
                return
            
            # Save all settings
            self.config_manager.set_default_base_name(default_name)
            self.config_manager.set_last_split_pages(split_pages)
            self.config_manager.set_last_split_size_mb(split_size)
            self.config_manager.set_ove_show_browser(self.ove_show_browser_var.get())
            self.config_manager.set_ove_auto_connect(self.ove_auto_connect_var.get())
            self.config_manager.set_section_names(self.section_names)
            
            # Watcher settings
            self.config_manager.set_watched_folders(self.watched_folders)
            self.config_manager.set_watch_auto_delete(self.watch_auto_delete_var.get())
            self.config_manager.set_watch_optimize_import(self.watch_optimize_import_var.get())
            
            # Save appearance mode (check for change)
            current_mode = self.config_manager.get_appearance_mode()
            appearance_display = self.appearance_var.get()
            new_mode = self._appearance_options.get(appearance_display, "dark")
            
            requires_restart = False
            if current_mode != new_mode:
                self.config_manager.set_appearance_mode(new_mode)
                requires_restart = True
            
            # Call callback if provided
            if self.on_save:
                self.on_save()
            
            msg = "Configuración guardada correctamente"
            if requires_restart:
                msg += "\n\n⚠️ El cambio de tema se aplicará al reiniciar la aplicación."
                
            messagebox.showinfo("Configuración", msg)
            self.destroy()
            
        except Exception as e:
            messagebox.showerror("Error", f"Error al guardar la configuración:\n{e}")
