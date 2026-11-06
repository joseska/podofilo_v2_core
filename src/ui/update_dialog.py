"""
Update Dialog - Diálogo modal de actualización de PodofiloV2.

Muestra la versión remota, tamaño, changelog y botones:
  - "Descargar e instalar" → descarga el setup + hash a %TEMP%, verifica
    SHA256 y lanza el instalador (la app se cierra).
  - "Recordarme más tarde" → cierra el diálogo (sigue siendo válida para
    el siguiente arranque automático del día).
  - "Ignorar esta versión" → escribe `ignored_update_version` en config y
    cierra el diálogo (no se volverá a mostrar hasta que cambie el tag).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Callable

import customtkinter as ctk
from tkinter import messagebox

from src.core.updater import (
    UpdateInfo,
    download_asset,
    verify_sha256,
    launch_and_exit,
    _update_staging_dir,
)
from src.ui.theme import get_button_style


def _human_size(num_bytes: int) -> str:
    """Convierte bytes a cadena legible (MiB)."""
    try:
        n = int(num_bytes)
    except Exception:
        return "?"
    if n <= 0:
        return "??"
    units = ["B", "KiB", "MiB", "GiB"]
    f = float(n)
    i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}"


class UpdateDialog(ctk.CTkToplevel):
    """Diálogo modal de actualización disponible."""

    def __init__(
        self,
        parent,
        config_manager,
        update_info: UpdateInfo,
        local_version: str = "",
    ):
        super().__init__(parent)
        self.config_manager = config_manager
        self.update_info = update_info
        self.local_version = local_version or ""

        self.title("Actualización disponible - Podofilo V2")
        self.geometry("560x540")
        self.minsize(480, 400)

        self.transient(parent)
        self.grab_set()

        self._is_downloading = False
        self._setup_ui()
        self.center_window()
        self.bind("<Escape>", lambda e: self._on_remind_later())

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1:
            width, height = 560, 540
        if self.master:
            px = self.master.winfo_x()
            py = self.master.winfo_y()
            pw = self.master.winfo_width()
            ph = self.master.winfo_height()
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
        else:
            x = (self.winfo_screenwidth() - width) // 2
            y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def _setup_ui(self):
        # Contenedor con dos vistas apiladas: info y progreso.
        self.info_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.info_frame.pack(fill="both", expand=True, padx=20, pady=20)
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        # (progress_frame se empaca al iniciar descarga)

        # --- Cabecera: versión ---
        header = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            header,
            text="Hay una nueva versión de Podofilo V2",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text=(
                f"Versión instalada: {self.local_version or '?'}   →   "
                f"Versión nueva: {self.update_info.tag}"
            ),
            font=("Segoe UI", 11),
            text_color="gray",
        ).pack(anchor="w", pady=(4, 0))

        # --- Tamaño del setup ---
        size_text = _human_size(self.update_info.setup_size)
        ctk.CTkLabel(
            self.info_frame,
            text=f"Tamaño de la descarga: {size_text}",
            font=("Segoe UI", 11),
            text_color="gray",
        ).pack(anchor="w", pady=(0, 4))

        # --- Changelog (cuerpo Markdown de la release) ---
        ctk.CTkLabel(
            self.info_frame,
            text="Novedades:",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(8, 4))

        body = (self.update_info.body or "").strip() or "(La release no incluye notas.)"
        changelog = ctk.CTkTextbox(
            self.info_frame,
            height=220,
            wrap="word",
            font=("Segoe UI", 11),
        )
        changelog.pack(fill="both", expand=True)
        changelog.insert("1.0", body)
        changelog.configure(state="disabled")

        # --- Botones info ---
        btn_row = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        btn_row.pack(fill="x", pady=(12, 0))

        ctk.CTkButton(
            btn_row,
            text="Ignorar esta versión",
            command=self._on_ignore_version,
            width=160,
            **get_button_style("ghost"),
        ).pack(side="left")

        ctk.CTkButton(
            btn_row,
            text="Recordarme más tarde",
            command=self._on_remind_later,
            width=160,
            **get_button_style("secondary"),
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btn_row,
            text="Descargar e instalar",
            command=self._on_download_and_install,
            width=180,
            **get_button_style("primary"),
        ).pack(side="right", padx=(6, 0))

        # --- Vista de progreso ---
        ctk.CTkLabel(
            self.progress_frame,
            text="Descargando actualización...",
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=(40, 10))

        ctk.CTkLabel(
            self.progress_frame,
            text=f"Versión {self.update_info.tag}",
            font=("Segoe UI", 11),
            text_color="gray",
        ).pack(pady=(0, 18))

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, width=440)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(0, 8))

        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="Iniciando...",
            font=("Segoe UI", 11),
            text_color="gray",
        )
        self.progress_label.pack(pady=(0, 6))

        self.progress_status = ctk.CTkLabel(
            self.progress_frame,
            text="",
            font=("Segoe UI", 10),
            text_color="gray",
        )
        self.progress_status.pack(pady=(4, 0))

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def _on_ignore_version(self):
        try:
            self.config_manager.set_ignored_update_version(self.update_info.tag)
        except Exception:
            pass
        self.destroy()

    def _on_remind_later(self):
        # Si ya empezamos a descargar, no dejamos cerrar (preventivo).
        if getattr(self, "_is_downloading", False):
            return
        self.destroy()

    def _on_download_and_install(self):
        if self._is_downloading:
            return
        self._is_downloading = True

        # Cambiar a vista de progreso.
        self.info_frame.pack_forget()
        self.progress_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Lanzar descarga en hilo separado (no bloquear UI).
        t = threading.Thread(target=self._download_worker, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Worker de descarga (hilo background)
    # ------------------------------------------------------------------
    def _download_worker(self):
        try:
            staging = _update_staging_dir()
            setup_path = staging / "PodofiloV2_Setup.exe"
            hash_path = staging / "PodofiloV2_Setup.exe.sha256"

            # 1) Descargar hash primero (ligero) para no esperar al grande sin info.
            self._set_progress(0.0, "Descargando suma de verificación...")
            if not download_asset(self.update_info.hash_url, hash_path):
                self._fail("No se pudo descargar la suma de verificación.")
                return

            # 2) Descargar setup con progreso.
            self._set_progress(0.0, "Descargando actualización...")

            def cb(downloaded: int, total: int):
                ratio = 0.0
                if total and total > 0:
                    ratio = max(0.0, min(1.0, downloaded / total))
                else:
                    # Sin content-length, aproximamos por tramos (~50MB).
                    ratio = max(0.0, min(1.0, downloaded / (50 * 1024 * 1024)))
                self._set_progress(
                    ratio,
                    f"{_human_size(downloaded)} de {_human_size(total) if total > 0 else '?'}",
                )

            if not download_asset(self.update_info.setup_url, setup_path, progress_cb=cb):
                self._fail("No se pudo descargar el instalador.")
                return

            # 3) Verificar SHA256.
            self._set_progress(1.0, "Verificando integridad...")
            if not verify_sha256(setup_path, hash_path):
                self._fail("La verificación de integridad (SHA256) ha fallado.")
                return

            # 4) Lanzar el instalador y cerrar la app.
            self._set_progress(1.0, "Instalando... la aplicación se cerrará.")
            # Pequeña espera para que la UI pinte el estado final.
            self.after(300, lambda: launch_and_exit(setup_path))
        except Exception as exc:
            self._fail(f"Error inesperado: {exc!r}")

    # ------------------------------------------------------------------
    # Helpers de UI desde hilo (thread-safe vía after)
    # ------------------------------------------------------------------
    def _set_progress(self, ratio: float, label: str):
        def _update():
            try:
                self.progress_bar.set(float(ratio))
                self.progress_label.configure(text=label or "")
            except Exception:
                pass
        self.after(0, _update)

    def _fail(self, message: str):
        def _update():
            self._is_downloading = False
            try:
                messagebox.showerror(
                    "Actualización fallida",
                    message + "\n\nPuedes reintentarlo más tarde desde "
                    "Configuración → General → Comprobar actualizaciones.",
                    parent=self,
                )
            except Exception:
                pass
            # Volver a la vista de info para permitir reintentar/cerrar.
            try:
                self.progress_frame.pack_forget()
                self.info_frame.pack(fill="both", expand=True, padx=20, pady=20)
                self.progress_label.configure(text="Iniciando...")
                self.progress_bar.set(0)
                self.progress_status.configure(text=message)
            except Exception:
                pass
        self.after(0, _update)