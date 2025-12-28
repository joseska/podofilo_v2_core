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

    def _wait_for_file_ready(self, file_path: str, stability_duration: float = 2.0, timeout: int = 30) -> bool:
        """
        Wait until file size stabilizes and it can be opened exclusively.
        - stability_duration: Time in seconds the size must remain constant.
        - timeout: Max wait time.
        """
        start_time = time.time()
        last_size = -1
        stable_start = None
        
        log.info(f"Waiting for file stabilization: {file_path}")

        while time.time() - start_time < timeout:
            try:
                # 0. Check if file exists
                if not Path(file_path).exists():
                    return False
                    
                # 1. Check size stability
                current_size = os.path.getsize(file_path)
                
                if current_size == last_size and current_size > 0:
                    if stable_start is None:
                        stable_start = time.time()
                    elif time.time() - stable_start >= stability_duration:
                        # 2. Final Lock Check (Try to rename or open exclusive)
                        try:
                            # Try to open in append mode to ensure no other writers
                            f = open(file_path, "a+b")
                            f.close()
                            log.info(f"File stabilized and unlocked: {current_size} bytes")
                            return True
                        except IOError:
                            # Still locked
                            pass
                else:
                    # Size changed or is 0, reset stability timer
                    last_size = current_size
                    stable_start = None
                    # log.debug(f"File growing... {current_size} bytes")

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

    def add_watch(self, path: str, patterns: List[str] = None):
        """Add a directory to watch list"""
        path_obj = Path(path)
        if not path_obj.exists():
            log.warning(f"Cannot watch non-existent path: {path}")
            return
            
        if path in self.watches:
            return

        try:
            handler = PdfEventHandler(self.callback, patterns)
            watch = self.observer.schedule(handler, str(path), recursive=False)
            self.watches[path] = watch
            log.info(f"Started watching: {path}")
        except Exception as e:
            log.error(f"Failed to watch {path}: {e}")

    def remove_watch(self, path: str):
        """Remove a directory from watch list"""
        if path in self.watches:
            try:
                self.observer.unschedule(self.watches[path])
                del self.watches[path]
                log.info(f"Stopped watching: {path}")
            except Exception as e:
                log.error(f"Error removing watch {path}: {e}")
