"""
Folder Watcher - Monitors directories for new PDF files
"""
import time
import os
import logging
import threading
from pathlib import Path
from typing import Callable, List, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

log = logging.getLogger(__name__)

class PdfEventHandler(FileSystemEventHandler):
    """
    Handles file system events for new PDFs
    Uses a debit/settle time to ensure file is fully written
    """
    
    def __init__(self, callback: Callable[[str], None], patterns: List[str] = None):
        super().__init__()
        self.callback = callback
        self.patterns = patterns or ["*.pdf"]
        self._pending_files = {}  # {path: timer}
        self._lock = threading.Lock()
        
    def _is_valid_file(self, path: str) -> bool:
        """Check if file matches patterns and is not a temp file"""
        path_obj = Path(path)
        
        # Check patterns
        import fnmatch
        match = any(fnmatch.fnmatch(path_obj.name.lower(), p.lower()) for p in self.patterns)
        if not match:
            return False
            
        # Ignore temp files
        if path_obj.name.startswith("~") or path_obj.name.startswith("."):
            return False
            
        return True

    def on_created(self, event):
        if event.is_directory:
            return
            
        if not self._is_valid_file(event.src_path):
            log.debug(f"File ignored (created, invalid): {event.src_path}")
            return
            
        log.info(f"File detected (created): {event.src_path}")
        self._schedule_processing(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
            
        # Optional: Handle modifications if needed, but usually create is enough for new files
        # Some scanners create empty file then write to it -> triggers modified
        if not self._is_valid_file(event.src_path):
            return
            
        # Log modified events para diagnóstico (solo si no está ya pendiente)
        with self._lock:
            if event.src_path not in self._pending_files:
                log.info(f"File detected (modified, new): {event.src_path}")
            else:
                log.debug(f"File detected (modified, debounce): {event.src_path}")
        
        # If we are already tracking this file, reset timer (debounce)
        # If not, it might be a file we missed creation for, or just an update
        # For safety, we can schedule it too
        self._schedule_processing(event.src_path)

    def _schedule_processing(self, file_path: str):
        """Schedule file for processing after settlement time"""
        with self._lock:
            # Cancel existing timer if any
            if file_path in self._pending_files:
                try:
                    self._pending_files[file_path].cancel()
                except Exception:
                    pass
            
            # Start new timer (wait for write to finish)
            # 1 second debounce usually enough for local moves, scanners might need more retry logic
            # which handle_file does
            timer = threading.Timer(1.0, self._process_file, args=[file_path])
            self._pending_files[file_path] = timer
            timer.start()

    def _process_file(self, file_path: str):
        """Called when file is presumably ready"""
        with self._lock:
            if file_path in self._pending_files:
                del self._pending_files[file_path]
        
        # Verify file is accessible (not locked by writing process)
        if self._wait_for_file_ready(file_path):
            try:
                self.callback(file_path)
            except Exception as e:
                log.error(f"Error in watcher callback for {file_path}: {e}")
        else:
            log.warning(f"File {file_path} failed to stabilize/open after retries")

    def _wait_for_file_ready(self, file_path: str, stability_duration: float = 1.0, timeout: int = 60) -> bool:
        """
        Wait until file size stabilizes and it can be opened exclusively.
        - stability_duration: Time in seconds the size must remain constant.
        - timeout: Max wait time.
        
        Nota: Timeout aumentado a 60s para manejar PDFs generados por Word/Excel
        que pueden tardar en escribirse completamente.
        """
        start_time = time.time()
        last_size = -1
        stable_start = None
        
        log.info(f"Waiting for file stabilization: {file_path}")

        while time.time() - start_time < timeout:
            try:
                # 0. Check if file exists
                if not Path(file_path).exists():
                    log.warning(f"File disappeared during stabilization: {file_path}")
                    return False
                    
                # 1. Check size stability
                current_size = os.path.getsize(file_path)
                
                if current_size == last_size and current_size > 0:
                    if stable_start is None:
                        stable_start = time.time()
                        log.debug(f"File size stable at {current_size} bytes, waiting {stability_duration}s...")
                    elif time.time() - stable_start >= stability_duration:
                        # 2. Final Lock Check (Try to open for reading)
                        # Nota: Usamos modo lectura en lugar de append porque Word/Excel
                        # pueden mantener locks de escritura incluso después de cerrar el documento,
                        # pero el archivo ya está completo y listo para leer.
                        try:
                            # Intentar abrir en modo lectura (menos restrictivo)
                            with open(file_path, "rb") as f:
                                # Verificar que el archivo tiene contenido válido
                                header = f.read(8)
                                if len(header) >= 4 and header[:4] == b'%PDF':
                                    elapsed = time.time() - start_time
                                    log.info(f"File stabilized and readable: {current_size} bytes (took {elapsed:.1f}s)")
                                    return True
                                else:
                                    log.warning(f"File readable but invalid PDF header: {header[:4] if header else 'empty'}")
                                    return False
                        except IOError as io_err:
                            # Still locked o no se puede leer
                            log.debug(f"File still locked or unreadable: {io_err}")
                            stable_start = None  # Reset y reintentar
                            pass
                else:
                    # Size changed or is 0, reset stability timer
                    if current_size != last_size:
                        if last_size >= 0:  # No loggear el primer cambio
                            log.debug(f"File size changed: {last_size} -> {current_size} bytes")
                    last_size = current_size
                    stable_start = None

                time.sleep(0.5)
                
            except Exception as e:
                log.warning(f"Error checking file {file_path}: {e}")
                time.sleep(1)
        
        log.warning(f"Timeout waiting for file {file_path}")
        return False


class WatcherManager:
    """Manages file system observers"""
    
    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback
        self.observer = Observer()
        self.watches = {}
        self.running = False
        self._initial_scan_done = set()  # Track folders already scanned
        
    def start(self):
        """Start the observer"""
        if not self.running:
            try:
                self.observer.start()
                self.running = True
                log.info("Watcher service started")
            except Exception as e:
                log.error(f"Failed to start watcher service: {e}")

    def stop(self):
        """Stop the observer"""
        if self.running:
            self.observer.stop()
            self.observer.join()
            self.running = False
            log.info("Watcher service stopped")

    def add_watch(self, path: str, patterns: List[str] = None, scan_existing: bool = True):
        """Add a directory to watch list
        
        Args:
            path: Directory path to watch
            patterns: File patterns to match (e.g., ['*.pdf'])
            scan_existing: If True, process existing files in the folder on first watch
        """
        path_obj = Path(path)
        if not path_obj.exists():
            log.warning(
                "La carpeta vigilada no existe: %s — créala o reconfigúrala en Ajustes", path
            )
            return
        # Validación de permisos de lectura/escritura: si oviscapto está configurado pero
        # el usuario no tiene permisos (red corporativa rara, ACL restrictiva, etc.),
        # informamos y no bloqueamos el arranque (otras carpetas pueden ser válidas).
        if not os.access(str(path_obj), os.R_OK):
            log.warning(
                "La carpeta vigilada no es legible: %s — revisa permisos", path
            )
            return
        if not os.access(str(path_obj), os.W_OK):
            # El watcher estrictamente solo necesita lectura, pero la app mueve ficheros
            # fuera de la carpeta vigilada (oviscapto): sin escritura, el move fallará.
            log.warning(
                "La carpeta vigilada no es escribible (el move de importaciones fallará): %s",
                path,
            )
            
        if path in self.watches:
            return

        try:
            handler = PdfEventHandler(self.callback, patterns)
            watch = self.observer.schedule(handler, str(path), recursive=False)
            self.watches[path] = watch
            log.info(f"Started watching: {path}")
            
            # Escanear archivos existentes si es la primera vez que vigilamos esta carpeta
            if scan_existing and path not in self._initial_scan_done:
                self._scan_existing_files(path, patterns or ["*.pdf"])
                self._initial_scan_done.add(path)
                
        except Exception as e:
            log.error(f"Failed to watch {path}: {e}")
    
    def _scan_existing_files(self, path: str, patterns: List[str]):
        """Escanea y procesa archivos existentes en la carpeta vigilada
        
        Este método se ejecuta una vez al iniciar el watcher para cargar PDFs
        que ya existían en la carpeta antes de arrancar Podofilo.
        """
        path_obj = Path(path)
        if not path_obj.is_dir():
            return
        
        import fnmatch
        found_files = []
        
        try:
            # Buscar archivos que coincidan con los patrones
            for item in path_obj.iterdir():
                if not item.is_file():
                    continue
                    
                # Verificar si coincide con algún patrón
                match = any(fnmatch.fnmatch(item.name.lower(), p.lower()) for p in patterns)
                if not match:
                    continue
                
                # Ignorar archivos temporales
                if item.name.startswith("~") or item.name.startswith("."):
                    continue
                
                found_files.append(str(item))
            
            if found_files:
                log.info(f"Found {len(found_files)} existing file(s) in {path}")
                # Procesar cada archivo en un thread separado para no bloquear
                for file_path in found_files:
                    threading.Thread(
                        target=self._process_existing_file,
                        args=(file_path,),
                        daemon=True
                    ).start()
            else:
                log.info(f"No existing files found in {path}")
                
        except Exception as e:
            log.error(f"Error scanning existing files in {path}: {e}")
    
    def _process_existing_file(self, file_path: str):
        """Procesa un archivo existente (similar a como lo haría el event handler)
        
        Usa la misma lógica de estabilización que los archivos nuevos para
        asegurar que el archivo no está siendo escrito por otro proceso.
        """
        try:
            # Crear un handler temporal solo para verificar estabilidad
            temp_handler = PdfEventHandler(self.callback, ["*.pdf"])
            
            # Esperar a que el archivo esté listo (por si está bloqueado)
            if temp_handler._wait_for_file_ready(file_path, stability_duration=0.5, timeout=5):
                log.info(f"Processing existing file: {file_path}")
                self.callback(file_path)
            else:
                log.warning(f"Existing file not accessible or locked: {file_path}")
        except Exception as e:
            log.error(f"Error processing existing file {file_path}: {e}")

    def remove_watch(self, path: str):
        """Remove a directory from watch list"""
        if path in self.watches:
            try:
                self.observer.unschedule(self.watches[path])
                del self.watches[path]
                log.info(f"Stopped watching: {path}")
            except Exception as e:
                log.error(f"Error removing watch {path}: {e}")
