import logging
import importlib.util
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)

def load_ove_extension() -> Optional[Dict[str, Any]]:
    """
    Attempts to load the OVE extension modules.
    
    Returns:
        A dictionary containing the extension modules and classes if successful,
        or None if the extension is not present.
        
        Keys:
        - 'ServiceModule': The 'service' module (access to OVEUnificadoService, DocumentInfo, helpers)
        - 'Manager': ShipmentManager class
        - 'UploadDialog': OVEUploadDialog class
        - 'ShipmentWindow': ShipmentWindow class
        - 'CredentialsDialog': OveCredentialsDialog class
    """
    try:
        # Check and import modules
        import src.extensions.ove.service as service_module
        from src.extensions.ove.manager import ShipmentManager
        from src.extensions.ove.ui.upload_dialog import OVEUploadDialog
        from src.extensions.ove.ui.shipment_window import ShipmentWindow
        from src.extensions.ove.ui.credentials_dialog import OveCredentialsDialog
        
        log.info("Extension OVE loaded successfully.")
        return {
            "ServiceModule": service_module,
            "Manager": ShipmentManager,
            "UploadDialog": OVEUploadDialog,
            "ShipmentWindow": ShipmentWindow,
            "CredentialsDialog": OveCredentialsDialog
        }
        
    except ImportError:
        log.info("Extension OVE not found. Running in Open Core mode.")
        return None
    except Exception as e:
        log.error(f"Error loading OVE extension: {e}")
        return None
