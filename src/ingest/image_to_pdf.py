"""Utilidades de conversión imagen -> PDF (A4).

Este módulo permite transformar imágenes (PNG/JPG/JPEG) en un PDF de una página,
para reutilizar el flujo PDF existente de la aplicación sin cambios estructurales.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image, ImageOps


# Tamaño A4 en puntos PDF (72 dpi lógicos).
A4_WIDTH_PT = 595.0
A4_HEIGHT_PT = 842.0

# Margen por defecto para que la imagen no quede pegada al borde de página.
DEFAULT_MARGIN_PT = 24.0


def _load_image_as_rgb_png_bytes(image_path: Path) -> tuple[bytes, int, int]:
    """Carga una imagen, corrige orientación EXIF y devuelve bytes PNG RGB.

    Devolvemos también `width_px` y `height_px` para calcular el layout en la página PDF.
    """
    with Image.open(image_path) as img:
        # Corregimos rotación EXIF para que la orientación final sea la esperada.
        img = ImageOps.exif_transpose(img)

        # Convertimos a RGB para evitar problemas con modos con alpha/paleta al insertar en PDF.
        if img.mode != "RGB":
            img = img.convert("RGB")

        width_px, height_px = img.size

        # Exportamos temporalmente a PNG en memoria para insertarlo en PyMuPDF sin ficheros intermedios.
        buff = BytesIO()
        img.save(buff, format="PNG", optimize=True)
        return buff.getvalue(), int(width_px), int(height_px)


def convert_image_file_to_pdf(
    image_path: Path,
    output_pdf_path: Path,
    *,
    margin_pt: float = DEFAULT_MARGIN_PT,
) -> Path:
    """Convierte una imagen local (PNG/JPG/JPEG) a un PDF A4 de una sola página.

    Si la imagen es apaisada, usa A4 horizontal para minimizar recortes visuales.
    """
    image_path = Path(image_path)
    output_pdf_path = Path(output_pdf_path)

    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError(f"Imagen no encontrada: {image_path}")

    image_bytes, width_px, height_px = _load_image_as_rgb_png_bytes(image_path)

    if width_px <= 0 or height_px <= 0:
        raise ValueError(f"Dimensiones inválidas de imagen: {width_px}x{height_px}")

    # Orientación de página: A4 vertical u horizontal según la proporción de la imagen.
    if width_px > height_px:
        page_width_pt, page_height_pt = A4_HEIGHT_PT, A4_WIDTH_PT
    else:
        page_width_pt, page_height_pt = A4_WIDTH_PT, A4_HEIGHT_PT

    # Área útil de dibujo dentro de márgenes.
    usable_w = max(1.0, page_width_pt - (2.0 * margin_pt))
    usable_h = max(1.0, page_height_pt - (2.0 * margin_pt))

    # Escalado tipo "contain": mantenemos proporción y ajustamos al área útil.
    scale = min(usable_w / float(width_px), usable_h / float(height_px))
    target_w = float(width_px) * scale
    target_h = float(height_px) * scale

    # Centramos la imagen en la página.
    x0 = (page_width_pt - target_w) / 2.0
    y0 = (page_height_pt - target_h) / 2.0
    draw_rect = fitz.Rect(x0, y0, x0 + target_w, y0 + target_h)

    doc = fitz.open()
    try:
        page = doc.new_page(width=page_width_pt, height=page_height_pt)
        page.insert_image(draw_rect, stream=image_bytes, keep_proportion=True)

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # Deflate + garbage reduce tamaño del PDF temporal.
        doc.save(str(output_pdf_path), garbage=4, deflate=True)
    finally:
        doc.close()

    return output_pdf_path
