import socket
import threading
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

PORT = 13013  # Puerto interno para Podofilo V2

def send_to_instance(payload):
    """Intenta enviar un mensaje a una instancia ya abierta."""
    try:
        if isinstance(payload, (list, tuple)):
            msg = {"files": [str(f) for f in payload] }
        elif isinstance(payload, dict):
            msg = payload
        else:
            msg = {"files": [] }

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(('127.0.0.1', PORT))
            data = json.dumps(msg)
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
                    chunks = []
                    try:
                        conn.settimeout(0.2)
                    except Exception:
                        pass
                    while True:
                        try:
                            part = conn.recv(4096)
                        except socket.timeout:
                            break
                        if not part:
                            break
                        chunks.append(part)
                        if len(part) < 4096:
                            break

                    data = b"".join(chunks)
                    if data:
                        try:
                            msg = json.loads(data.decode('utf-8'))
                            files = msg.get("files", []) if isinstance(msg, dict) else []
                            log.info(f"Instancia única activada. Archivos: {len(files)}")
                            self.app_callback(msg)
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
