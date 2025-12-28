"""
Podofilo V2 - Modern PDF Management Application
Entry point for the application
"""
import argparse
import logging
from pathlib import Path

APP_VERSION_LABEL = "V2_25_12_2025"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# logging.basicConfig(
#     level=logging.DEBUG,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )

# Asegurar que el módulo principal de la UI emita DEBUG aunque otros modifiquen niveles
logging.getLogger("src.ui.main_window").setLevel(logging.DEBUG)
log = logging.getLogger(__name__)

def _parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Podofilo V2 - Gestor moderno de PDFs"
    )
    parser.add_argument(
        "pdf",
        nargs="*",
        help="Ruta(s) de archivos PDF que se abrirán automáticamente al iniciar",
    )
    return parser.parse_args()

def main():
    """Main entry point"""
    log.info("Starting Podofilo V2...")
    
    args = _parse_args()
    initial_files = [Path(p).resolve() for p in getattr(args, "pdf", [])] # Usar resolve para rutas absolutas

    # --- SINGLE INSTANCE CHECK ---
    from src.core.single_instance import send_to_instance
    if send_to_instance(initial_files):
        log.info("Archivos enviados a la instancia ya abierta. Cerrando esta instancia.")
        return # Salir si se enviaron con éxito

    if initial_files:
        log.info(
            "Se solicitaron %d archivo(s) para apertura inicial", len(initial_files)
        )
    
    # Import UI after logging is configured
    from src.ui.main_window import PodofiloApp
    
    # Create and run application
    app = PodofiloApp(initial_files=initial_files, version_label=APP_VERSION_LABEL)
    app.run()

if __name__ == "__main__":
    main()
