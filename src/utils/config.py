import json
import os
from pathlib import Path
from typing import List, Dict, Any

class ConfigManager:
    """Manages application configuration and persistent state"""
    
    def __init__(self):
        # Changed from .podofilo to podofilo for visibility
        self.config_dir = Path.home() / "podofilo"
        self.config_file = self.config_dir / "config_v2.json"
        
        # Migration: Check for old hidden config and migrate if new one doesn't exist
        old_config_dir = Path.home() / ".podofilo"
        old_config_file = old_config_dir / "config_v2.json"
        
        if not self.config_file.exists() and old_config_file.exists():
            try:
                self._ensure_config_dir()
                import shutil
                shutil.copy2(old_config_file, self.config_file)
                print(f"Migrated config from {old_config_file} to {self.config_file}")
            except Exception as e:
                print(f"Error migrating config: {e}")

        self._ensure_config_dir()
        self._ensure_config_dir()
        self.config = self._load_config()
        
        # Merge with defaults to ensure new keys exist
        defaults = self._get_default_config()
        changed = False
        for key, val in defaults.items():
            if key not in self.config:
                self.config[key] = val
                changed = True
        
        if changed:
            self.save()
        
    def _ensure_config_dir(self):
        """Ensure configuration directory exists"""
        if not self.config_dir.exists():
            self.config_dir.mkdir(parents=True)
            
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        if not self.config_file.exists():
            return self._get_default_config()
            
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return self._get_default_config()
            
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "section_names": [
                "1 ACUERDO DE DEVOLUCION",
                "2 RECURSO DE ALZADA EN TRAMITE",
                "3 RECURSO CONTENCIOSO",
                "3 AUTO MC"
            ],
            "default_base_name": "resultado",
            "last_split_pages": 6,
            "last_split_size_mb": 5,
            "ove_show_browser": False,
            "ove_auto_connect": False,
            "ove_last_expediente": "",
            "appearance_mode": "dark",
            "window_geometry": {
                "width": 1280,
                "height": 720,
                "x": None,
                "y": None,
                "is_maximized": False,
            },
            "thumbnail_size": 150,
            "continuous_mode": False,
            # Default watch path: %LOCALAPPDATA%\oviscapto
            "watched_folders": [str(Path.home() / "AppData" / "Local" / "oviscapto")],
            "watch_auto_delete": False,
            "watch_patterns": ["*.pdf"],
            "last_loaded_dir": str(Path.home() / "Documents"),
        }
        
    def save(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")
            
    def get_section_names(self) -> List[str]:
        """Get list of predefined section names"""
        return self.config.get("section_names", [])
        
    def set_section_names(self, names: List[str]):
        """Set list of predefined section names"""
        self.config["section_names"] = names
        self.save()
        
    def get_default_base_name(self) -> str:
        """Get default base name for new sections"""
        return self.config.get("default_base_name", "resultado")
        
    def set_default_base_name(self, name: str):
        """Set default base name for new sections"""
        self.config["default_base_name"] = name
        self.save()

    def get_last_split_pages(self) -> int:
        """Get last used split pages count"""
        return self.config.get("last_split_pages", 6)

    def set_last_split_pages(self, pages: int):
        """Set last used split pages count"""
        self.config["last_split_pages"] = pages
        self.save()

    def get_last_split_size_mb(self) -> int:
        """Get last used split size in MB"""
        return self.config.get("last_split_size_mb", 5)

    def set_last_split_size_mb(self, size_mb: int):
        """Set last used split size in MB"""
        self.config["last_split_size_mb"] = size_mb
        self.save()

    # --------------------------
    # OVE integration settings
    # --------------------------

    def get_ove_show_browser(self) -> bool:
        return self.config.get("ove_show_browser", False)

    def set_ove_show_browser(self, value: bool):
        self.config["ove_show_browser"] = bool(value)
        self.save()

    def get_ove_auto_connect(self) -> bool:
        return self.config.get("ove_auto_connect", False)

    def set_ove_auto_connect(self, value: bool):
        self.config["ove_auto_connect"] = bool(value)
        self.save()

    def get_ove_last_expediente(self) -> str:
        return self.config.get("ove_last_expediente", "")

    def set_ove_last_expediente(self, expediente: str):
        self.config["ove_last_expediente"] = expediente or ""
        self.save()

    # --------------------------
    # Appearance settings
    # --------------------------

    def get_appearance_mode(self) -> str:
        """Get appearance mode: 'dark', 'light', or 'system'"""
        return self.config.get("appearance_mode", "dark")

    def set_appearance_mode(self, mode: str):
        """Set appearance mode: 'dark', 'light', or 'system'"""
        if mode in ("dark", "light", "system"):
            self.config["appearance_mode"] = mode
            self.save()

    def get_window_geometry(self) -> Dict[str, Any]:
        """Get saved window geometry"""
        default_geometry = self._get_default_config()["window_geometry"]
        geometry = self.config.get("window_geometry", default_geometry)

        # Ensure all expected keys exist to avoid KeyError
        for key, value in default_geometry.items():
            geometry.setdefault(key, value)

        return geometry

    def set_window_geometry(
        self,
        width: int,
        height: int,
        x: int | None,
        y: int | None,
        is_maximized: bool,
    ):
        """Persist window geometry and maximized state"""
        self.config["window_geometry"] = {
            "width": width,
            "height": height,
            "x": x,
            "y": y,
            "is_maximized": is_maximized,
        }
        self.save()

    # --------------------------
    # Zoom / Thumbnail size
    # --------------------------

    def get_thumbnail_size(self) -> int:
        """Get saved thumbnail size (zoom level)"""
        return self.config.get("thumbnail_size", 150)

    def set_thumbnail_size(self, size: int):
        """Set thumbnail size (zoom level)"""
        self.config["thumbnail_size"] = size
        self.save()

    # --------------------------
    # View mode settings
    # --------------------------

    def get_continuous_mode(self) -> bool:
        """Get continuous view mode state"""
        return self.config.get("continuous_mode", False)

    def set_continuous_mode(self, enabled: bool):
        """Set continuous view mode state"""
        self.config["continuous_mode"] = bool(enabled)
        self.save()

    # --------------------------
    # Watcher settings
    # --------------------------

    def get_watched_folders(self) -> List[str]:
        """Get list of watched folder paths"""
        return self.config.get("watched_folders", [])

    def set_watched_folders(self, folders: List[str]):
        """Set list of watched folder paths"""
        # Filter unique and non-empty
        unique_folders = sorted(list(set(f for f in folders if f and f.strip())))
        self.config["watched_folders"] = unique_folders
        self.save()

    def add_watched_folder(self, folder: str):
        """Add a folder to watch list"""
        folders = self.get_watched_folders()
        if folder not in folders:
            folders.append(folder)
            self.set_watched_folders(folders)

    def remove_watched_folder(self, folder: str):
        """Remove a folder from watch list"""
        folders = self.get_watched_folders()
        if folder in folders:
            folders.remove(folder)
            self.set_watched_folders(folders)

    def get_watch_auto_delete(self) -> bool:
        """Get whether to auto-delete imported files"""
        return self.config.get("watch_auto_delete", False)

    def set_watch_auto_delete(self, enabled: bool):
        """Set whether to auto-delete imported files"""
        self.config["watch_auto_delete"] = bool(enabled)
        self.save()

    def get_watch_optimize_import(self) -> bool:
        """Get whether to optimize imported files (compress)"""
        return self.config.get("watch_optimize_import", True)

    def set_watch_optimize_import(self, enabled: bool):
        """Set whether to optimize imported files (compress)"""
        self.config["watch_optimize_import"] = bool(enabled)
        self.save()

    def get_watch_patterns(self) -> List[str]:
        """Get list of file patterns to watch (default: ['*.pdf'])"""
        return self.config.get("watch_patterns", ["*.pdf"])

    # --------------------------
    # Persistence for last loaded directory
    # --------------------------

    def get_last_loaded_dir(self) -> str:
        """Get the last directory from which a file was loaded"""
        path = self.config.get("last_loaded_dir")
        if path and Path(path).exists():
            return path
        return str(Path.home() / "Documents")

    def set_last_loaded_dir(self, directory: str):
        """Set the last directory from which a file was loaded"""
        if directory:
            self.config["last_loaded_dir"] = str(directory)
            self.save()

    # --------------------------
    # Persistence for Doc Signature Map (Signature Memory)
    # --------------------------

    def get_doc_signature_map(self) -> Dict[str, str]:
        """Get the map of {document_name: signature_type_name}"""
        return self.config.get("doc_signature_map", {})

    def set_doc_signature_map(self, signature_map: Dict[str, str]):
        """Set the map of {document_name: signature_type_name}"""
        self.config["doc_signature_map"] = signature_map
        self.save()

