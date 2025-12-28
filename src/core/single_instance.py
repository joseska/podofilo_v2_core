import socket
import threading
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

PORT = 13013  # Puerto interno para Podofilo V2

def send_to_instance(files):
    """
    Intenta enviar una lista de archivos a una instancia ya abierta.
    Retorna True si tuvo éxito, False si no hay ninguna instancia escuchando.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(('127.0.0.1', PORT))
            data = json.dumps({"files": [str(f) for f in files]})
            s.sendall(data.encode('utf-8'))
            return True
    except (ConnectionRefusedError, socket.timeout):
        return False
    except Exception as e:
        log.debug(f"Error intentando comunicar con instancia: {e}")
        return False

class InstanceServer:
    """
    Servidor que escucha en segundo plano para recibir nuevos archivos.
    """
    def __init__(self, app_callback):
        self.app_callback = app_callback
        self.running = False
        self.server_sock = None

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self):
        try:
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Reutilizar puerto si se cerró mal recientemente
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock.bind(('127.0.0.1', PORT))
            self.server_sock.listen(5)
            log.info(f"Servidor de instancia única escuchando en puerto {PORT}")
            
            while self.running:
                conn, addr = self.server_sock.accept()
                with conn:
                    data = conn.recv(1024 * 10) # 10KB sobra para rutas
                    if data:
                        try:
                            msg = json.loads(data.decode('utf-8'))
                            files = msg.get("files", [])
                            # Siempre llamamos al callback, si no hay archivos es para enfocar
                            log.info(f"Instancia única activada. Archivos: {len(files)}")
                            self.app_callback(files)
                        except Exception as e:
                            log.error(f"Error procesando mensaje de instancia: {e}")
        except Exception as e:
            if self.running:
                log.error(f"Error en el servidor de instancia única: {e}")
        finally:
            if self.server_sock:
                self.server_sock.close()

    def stop(self):
        self.running = False
        if self.server_sock:
            # Crear conexión dummy para desbloquear el accept()
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)
                    s.connect(('127.0.0.1', PORT))
            except:
                pass
            self.server_sock.close()
