import customtkinter as ctk
import tkinter as tk
from typing import List, Optional, Callable
import threading
import queue

from src.ui.theme import get_theme, get_button_style, get_input_style

class CenteredInputDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, text: str, initial_value: str = ""):
        super().__init__(parent)
        self.title(title)
        self.text = text
        self.initial_value = initial_value
        self.result = None
        
        self.geometry("300x150")
        self.resizable(False, False)
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._setup_ui()
        self.center_window()
        
        self.wait_window()

    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        
        if self.master:
            try:
                parent_x = self.master.winfo_x()
                parent_y = self.master.winfo_y()
                parent_width = self.master.winfo_width()
                parent_height = self.master.winfo_height()
                
                x = parent_x + (parent_width // 2) - (width // 2)
                y = parent_y + (parent_height // 2) - (height // 2)
            except:
                x = (self.winfo_screenwidth() // 2) - (width // 2)
                y = (self.winfo_screenheight() // 2) - (height // 2)
        else:
            x = (self.winfo_screenwidth() // 2) - (width // 2)
            y = (self.winfo_screenheight() // 2) - (height // 2)
            
        self.geometry(f'{width}x{height}+{x}+{y}')
        
    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=0)
        
        # Increased top padding to prevent text cutoff
        # Explicit text color to ensure visibility
        ctk.CTkLabel(self, text=self.text, text_color=("black", "white"), font=("Segoe UI", 11)).grid(row=0, column=0, padx=20, pady=(30, 10))
        
        self.entry = ctk.CTkEntry(self, font=("Segoe UI", 11), corner_radius=1)
        self.entry.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        if self.initial_value:
            self.entry.insert(0, self.initial_value)
            
        self.entry.bind("<Return>", self._on_ok)
        self.entry.bind("<Escape>", self._on_cancel)
        
        # Schedule focus and selection after window is fully rendered
        self.after(50, self._set_focus_and_select)
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=20, pady=20)
        
        ctk.CTkButton(btn_frame, text="OK", width=100, command=self._on_ok, **get_button_style("primary")).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", width=100, command=self._on_cancel, **get_button_style("secondary")).pack(side="right", padx=5)
        
    def _set_focus_and_select(self):
        """Set focus to entry and select all text"""
        self.entry.focus_force()
        if self.initial_value:
            # Select all text so user can start typing immediately
            self.entry.select_range(0, tk.END)
            # Move cursor to end (selection will still be active)
            self.entry.icursor(tk.END)
    
    def _on_ok(self, event=None):
        self.result = self.entry.get()
        self.destroy()
        
    def _on_cancel(self, event=None):
        self.result = None
        self.destroy()
        
    def get_input(self):
        return self.result



class SectionNamesEditorDialog(ctk.CTkToplevel):
    """Dialog to edit section name presets"""
    def __init__(self, parent, current_names: List[str], default_base: str, on_save):
        super().__init__(parent)
        self.title("Editar lista de nombres")
        self.on_save = on_save
        self.names = list(current_names)
        self.default_base = default_base
        
        # Resize to 750x600 (50% larger than 500x400)
        self.geometry("750x600")
        self.resizable(True, True)
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._setup_ui()
        self.center_window()
        
    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        
        if self.master:
            try:
                parent_x = self.master.winfo_x()
                parent_y = self.master.winfo_y()
                parent_width = self.master.winfo_width()
                parent_height = self.master.winfo_height()
                
                x = parent_x + (parent_width // 2) - (width // 2)
                y = parent_y + (parent_height // 2) - (height // 2)
            except:
                x = (self.winfo_screenwidth() // 2) - (width // 2)
                y = (self.winfo_screenheight() // 2) - (height // 2)
        else:
            x = (self.winfo_screenwidth() // 2) - (width // 2)
            y = (self.winfo_screenheight() // 2) - (height // 2)
            
        self.geometry(f'{width}x{height}+{x}+{y}')
        
    def _setup_ui(self):
        # Top frame for base name
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(top_frame, text="Nombre predeterminado:", font=("Segoe UI", 11)).pack(side="left", padx=5)
        self.base_entry = ctk.CTkEntry(top_frame, font=("Segoe UI", 11), corner_radius=1)
        self.base_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.base_entry.insert(0, self.default_base)
        
        # Toolbar frame
        toolbar = ctk.CTkFrame(self)
        toolbar.pack(fill="x", padx=10, pady=(0, 5))
        
        # Buttons
        # Using unicode chars for simplicity
        ctk.CTkButton(toolbar, text="✏️", width=40, command=self.edit_item).pack(side="left", padx=2, pady=2)
        ctk.CTkButton(toolbar, text="➕", width=40, command=self.add_item).pack(side="left", padx=2, pady=2)
        ctk.CTkButton(toolbar, text="❌", width=40, command=self.remove_item, fg_color="#C9302C", hover_color="#A9201C").pack(side="left", padx=2, pady=2)
        
        ctk.CTkButton(toolbar, text="⬇️", width=40, command=self.move_down).pack(side="right", padx=2, pady=2)
        ctk.CTkButton(toolbar, text="⬆️", width=40, command=self.move_up).pack(side="right", padx=2, pady=2)
        
        # List frame
        list_frame = ctk.CTkFrame(self)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Scrollbar
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        # Listbox (Standard Tkinter because CTk doesn't have one yet)
        self.listbox = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            font=("Segoe UI", 11),
            bd=0,
            highlightthickness=0,
            activestyle="none",
            yscrollcommand=scrollbar.set
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        
        # Populate list
        for name in self.names:
            self.listbox.insert(tk.END, name)
            
        # Double click to edit
        self.listbox.bind("<Double-Button-1>", lambda e: self.edit_item())
        
        # Bottom buttons
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkButton(bottom_frame, text="Guardar", command=self.save, **get_button_style("primary")).pack(side="right", padx=5)
        ctk.CTkButton(bottom_frame, text="Cancelar", command=self.destroy, **get_button_style("secondary")).pack(side="right", padx=5)
        
    def add_item(self):
        dialog = CenteredInputDialog(self, "Agregar Nombre", "Nombre:")
        name = dialog.get_input()
        if name:
            self.names.append(name)
            self.listbox.insert(tk.END, name)
            self.listbox.see(tk.END)
            
    def edit_item(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        current = self.names[idx]
        
        # Pass initial_value directly
        dialog = CenteredInputDialog(self, "Editar Nombre", "Nombre:", initial_value=current)
        
        new_name = dialog.get_input()
        if new_name:
            self.names[idx] = new_name
            self.listbox.delete(idx)
            self.listbox.insert(idx, new_name)
            self.listbox.selection_set(idx)
            
    def remove_item(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.names.pop(idx)
        self.listbox.delete(idx)
        
        # Select next if available
        if idx < self.listbox.size():
            self.listbox.selection_set(idx)
        elif self.listbox.size() > 0:
            self.listbox.selection_set(self.listbox.size() - 1)
            
    def move_up(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx > 0:
            # Swap in list
            self.names[idx], self.names[idx-1] = self.names[idx-1], self.names[idx]
            
            # Swap in listbox
            text = self.listbox.get(idx)
            self.listbox.delete(idx)
            self.listbox.insert(idx-1, text)
            self.listbox.selection_set(idx-1)
            self.listbox.see(idx-1)
            
    def move_down(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self.names) - 1:
            # Swap in list
            self.names[idx], self.names[idx+1] = self.names[idx+1], self.names[idx]
            
            # Swap in listbox
            text = self.listbox.get(idx)
            self.listbox.delete(idx)
            self.listbox.insert(idx+1, text)
            self.listbox.selection_set(idx+1)
            self.listbox.see(idx+1)
            
    def save(self):
        base_name = self.base_entry.get()
        self.on_save(self.names, base_name)
        self.destroy()


class ProgressDialog(ctk.CTkToplevel):
    """
    Diálogo de progreso no bloqueante para operaciones largas.
    Ejecuta una tarea en un hilo separado mientras muestra progreso.
    """
    def __init__(self, parent, title: str, message: str, 
                 task: Optional[Callable] = None,
                 cancellable: bool = True):
        super().__init__(parent)
        self.title(title)
        self._message = message
        self._task = task
        self._cancellable = cancellable
        self._cancelled = False
        self._completed = False
        self._error: Optional[Exception] = None
        self._result = None
        
        # Cola para comunicación entre hilos
        self._queue = queue.Queue()
        
        self.geometry("400x150")
        self.resizable(False, False)
        
        # Modal
        self.transient(parent)
        self.grab_set()
        
        # Prevenir cierre con X si no es cancelable
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        
        self._setup_ui()
        self.center_window()
        
        # Iniciar tarea si se proporcionó
        if self._task:
            self.after(100, self._start_task)
    
    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        
        if self.master:
            try:
                parent_x = self.master.winfo_x()
                parent_y = self.master.winfo_y()
                parent_width = self.master.winfo_width()
                parent_height = self.master.winfo_height()
                
                x = parent_x + (parent_width // 2) - (width // 2)
                y = parent_y + (parent_height // 2) - (height // 2)
            except:
                x = (self.winfo_screenwidth() // 2) - (width // 2)
                y = (self.winfo_screenheight() // 2) - (height // 2)
        else:
            x = (self.winfo_screenwidth() // 2) - (width // 2)
            y = (self.winfo_screenheight() // 2) - (height // 2)
            
        self.geometry(f'{width}x{height}+{x}+{y}')
    
    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        
        # Mensaje
        self.message_label = ctk.CTkLabel(
            self, 
            text=self._message,
            font=("Segoe UI", 11),
            wraplength=350
        )
        self.message_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        
        # Barra de progreso
        self.progress_bar = ctk.CTkProgressBar(self, width=350)
        self.progress_bar.grid(row=1, column=0, padx=20, pady=10)
        self.progress_bar.set(0)
        
        # Etiqueta de detalle (archivo actual, etc.)
        self.detail_label = ctk.CTkLabel(
            self,
            text="",
            font=("Segoe UI", 9),
            text_color="gray"
        )
        self.detail_label.grid(row=2, column=0, padx=20, pady=(0, 5))
        
        # Botón cancelar (solo si es cancelable)
        self.cancel_btn = None
        if self._cancellable:
            self.cancel_btn = ctk.CTkButton(
                self,
                text="Cancelar",
                width=100,
                command=self._on_cancel,
                **get_button_style("secondary")
            )
            self.cancel_btn.grid(row=3, column=0, pady=(5, 15))
        else:
            # Ajustar altura si no hay botón
            self.geometry("400x120")
    
    def _on_close_request(self):
        """Manejar intento de cerrar ventana"""
        if self._cancellable and not self._completed:
            self._on_cancel()
        elif self._completed:
            self.destroy()
    
    def _on_cancel(self):
        """Manejar cancelación"""
        self._cancelled = True
        if hasattr(self, 'cancel_btn'):
            self.cancel_btn.configure(state="disabled", text="Cancelando...")
    
    def _start_task(self):
        """Iniciar tarea en hilo separado"""
        def worker():
            try:
                self._result = self._task(self)
            except Exception as e:
                self._error = e
            finally:
                self._queue.put(("done", None))
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        
        # Iniciar polling de la cola
        self._poll_queue()
    
    def _poll_queue(self):
        """Procesar mensajes de la cola"""
        try:
            while True:
                msg_type, data = self._queue.get_nowait()
                
                if msg_type == "progress":
                    value, detail = data
                    self.progress_bar.set(value)
                    if detail:
                        self.detail_label.configure(text=detail)
                    # Forzar actualización de la UI
                    self.update_idletasks()
                
                elif msg_type == "message":
                    self.message_label.configure(text=data)
                    self.update_idletasks()
                
                elif msg_type == "done":
                    self._completed = True
                    self.destroy()
                    return
                    
        except queue.Empty:
            pass
        
        # Continuar polling si no ha terminado - más frecuente para mejor respuesta
        if not self._completed:
            self.after(16, self._poll_queue)  # ~60fps
    
    def update_progress(self, value: float, detail: str = ""):
        """
        Actualizar progreso desde el hilo de trabajo.
        value: 0.0 a 1.0
        detail: texto descriptivo opcional
        """
        self._queue.put(("progress", (value, detail)))
    
    def update_message(self, message: str):
        """Actualizar mensaje principal desde el hilo de trabajo"""
        self._queue.put(("message", message))
    
    @property
    def is_cancelled(self) -> bool:
        """Verificar si el usuario canceló la operación"""
        return self._cancelled
    
    @property
    def error(self) -> Optional[Exception]:
        """Obtener error si ocurrió"""
        return self._error
    
    @property
    def result(self):
        """Obtener resultado de la tarea"""
        return self._result
    
    def run_and_wait(self):
        """Ejecutar y esperar a que termine. Retorna el resultado."""
        # Usar un loop que procesa eventos en lugar de wait_window
        # para evitar bloquear completamente la UI
        while not self._completed:
            try:
                self.update()
                self.update_idletasks()
            except:
                break
            import time
            time.sleep(0.01)
        
        if self._error:
            raise self._error
        return self._result
