"""
PDF Document Handler - PyMuPDF based
Replaces rupdf with modern PyMuPDF (fitz)
"""
import errno
import logging
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image
import io

log = logging.getLogger(__name__)


def translate_save_error(exc: Exception, output_path: str):
    """Re-raise PyMuPDF permission errors as PermissionError with context."""
    if isinstance(exc, PermissionError):
        raise
    message = str(exc)
    lower = message.lower()
    if (
        getattr(exc, "errno", None) == errno.EACCES
        or "permission denied" in lower
        or "access is denied" in lower
        or "cannot remove file" in lower
    ):
        raise PermissionError(
            f"No se pudo guardar '{output_path}' porque el archivo está en uso o no hay permisos. "
            "Cierra cualquier visor que lo tenga abierto o elige otra ubicación."
        ) from exc


class PdfDocument:
    """Wrapper for PDF document operations using PyMuPDF"""
    
    def __init__(self, filepath: str):
        """Load PDF from file"""
        self.filepath = Path(filepath)
        self._file_buffer = self.filepath.read_bytes()
        self.doc = fitz.open(stream=self._file_buffer, filetype="pdf")
        log.info(f"Loaded PDF: {self.filepath.name} ({self.page_count} pages)")
    
    @property
    def page_count(self) -> int:
        """Get number of pages"""
        return len(self.doc)
    
    def get_page(self, page_num: int) -> fitz.Page:
        """Get page object (0-indexed)"""
        if 0 <= page_num < self.page_count:
            return self.doc[page_num]
        raise IndexError(f"Page {page_num} out of range (0-{self.page_count-1})")
    
    def get_page_size(self, page_num: int) -> Tuple[float, float]:
        """Get page size in points (width, height)"""
        page = self.get_page(page_num)
        rect = page.rect
        return (rect.width, rect.height)
    
    def render_page_thumbnail(self, page_num: int, dpi: int = 72) -> Image.Image:
        """
        Render page as PIL Image for thumbnail
        
        Args:
            page_num: Page number (0-indexed)
            dpi: Resolution for rendering
            
        Returns:
            PIL Image object
        """
        page = self.get_page(page_num)
        
        # Calculate zoom factor from DPI
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        
        # Render to pixmap
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Convert to PIL Image
        img_data = pix.tobytes("ppm")
        img = Image.open(io.BytesIO(img_data))
        
        return img
    
    def rotate_page(self, page_num: int, rotation: int):
        """
        Rotate page by 90, 180, or 270 degrees (incremental)
        
        Args:
            page_num: Page number (0-indexed)
            rotation: Rotation angle to add (90, 180, 270)
        """
        if rotation not in [90, 180, 270, -90, -180, -270]:
            raise ValueError("Rotation must be 90, 180, or 270 degrees")
        
        page = self.get_page(page_num)
        # Get current rotation and add the new rotation
        current_rotation = page.rotation
        new_rotation = (current_rotation + rotation) % 360
        page.set_rotation(new_rotation)
        log.debug(f"Rotated page {page_num} from {current_rotation}° to {new_rotation}°")
    
    def extract_text(self, page_num: int) -> str:
        """Extract text from page"""
        page = self.get_page(page_num)
        return page.get_text()
    
    def is_page_blank(self, page_num: int, threshold: float = 0.001) -> bool:
        """
        Detect if a page is blank by analyzing pixel content
        
        Args:
            page_num: Page number (0-indexed)
            threshold: Threshold for blank detection (lower = stricter)
            
        Returns:
            True if page appears blank
        """
        try:
            page = self.get_page(page_num)
            
            # Get page dimensions
            rect = page.rect
            w, h = rect.width, rect.height
            
            # Scale down for faster analysis (like V1: max(w/1200, h/1200, 1))
            max_scale = max(w/1200, h/1200, 1)
            zoom = 1.0 / max_scale
            mat = fitz.Matrix(zoom, zoom)
            
            # Render to grayscale pixmap with margin clipping (10mm margin like V1)
            pt_to_mm = 25.4 / 72
            margin_mm = 10
            margin_pt = margin_mm / pt_to_mm
            
            if w > 50/pt_to_mm and h > 50/pt_to_mm:
                clip = fitz.Rect(
                    margin_pt,
                    margin_pt,
                    w - margin_pt,
                    h - margin_pt
                )
            else:
                clip = None
            
            # Render to grayscale
            pix = page.get_pixmap(matrix=mat, colorspace="gray", alpha=False, clip=clip)
            
            # Analyze pixels - calculate average darkness
            # PyMuPDF pixels are in range 0-255 (0=black, 255=white)
            samples = pix.samples
            total_pixels = len(samples)
            
            if total_pixels == 0:
                return True
            
            # Calculate average pixel value (0=black, 255=white)
            avg_value = sum(samples) / total_pixels
            
            # Normalize to 0-1 range (1=white, 0=black)
            normalized = avg_value / 255.0
            
            # V1 uses binary_closing_average which returns low values for blank pages
            # We invert: blank pages have high normalized values (close to 1)
            # So we calculate "darkness" as (1 - normalized)
            darkness = 1.0 - normalized
            
            # Page is blank if darkness is below threshold
            is_blank = darkness < threshold
            
            log.debug(f"Page {page_num} blank check: darkness={darkness:.4f}, threshold={threshold}, blank={is_blank}")
            
            return is_blank
            
        except Exception as e:
            log.error(f"Error checking if page {page_num} is blank: {e}")
            return False
    
    def extract_images(self, page_num: int) -> List[dict]:
        """Extract images from page"""
        page = self.get_page(page_num)
        return page.get_images()
    
    def delete_page(self, page_num: int):
        """Delete a page"""
        self.doc.delete_page(page_num)
        log.debug(f"Deleted page {page_num}")
    
    def insert_page(self, page_num: int, width: float = 595, height: float = 842):
        """
        Insert blank page
        
        Args:
            page_num: Position to insert (0-indexed)
            width: Page width in points (default A4: 595)
            height: Page height in points (default A4: 842)
        """
        self.doc.new_page(pno=page_num, width=width, height=height)
        log.debug(f"Inserted blank page at {page_num}")
    
    def save(self, output_path: str, garbage: int = 4, deflate: bool = True):
        """
        Save PDF to file
        
        Args:
            output_path: Output file path
            garbage: Garbage collection level (0-4, 4=max)
            deflate: Use deflate compression
        """
        try:
            self.doc.save(output_path, garbage=garbage, deflate=deflate)
            log.info(f"Saved PDF to {output_path}")
        except Exception as exc:
            translate_save_error(exc, output_path)
            raise
        
    def save_subset(self, output_path: str, pages: List[int], garbage: int = 4, deflate: bool = True):
        """
        Save subset of pages to a new PDF file
        
        Args:
            output_path: Output file path
            pages: List of page indices to include (0-indexed)
            garbage: Garbage collection level
            deflate: Use deflate compression
        """
        new_doc = fitz.open()
        new_doc.insert_pdf(self.doc, from_page=pages[0], to_page=pages[-1])
        # Note: insert_pdf with range assumes contiguous if using from/to. 
        # If pages is disjoint, we should loop or use selection.
        # Given sections are contiguous ranges, from_page/to_page works and is efficient.
        # But let's be robust:
        # new_doc.insert_pdf(self.doc, from_page=-1, to_page=-1) # copy metadata?
        
        # Safer way for arbitrary list of pages:
        # new_doc.select(pages) -> modifies in place! don't do that.
        
        # Correct approach for ranges (sections are ranges):
        # If pages are contiguous:
        if not pages:
            return
            
        start = pages[0]
        end = pages[-1]
        
        # Check contiguous
        if len(pages) == (end - start + 1):
             new_doc.insert_pdf(self.doc, from_page=start, to_page=end)
        else:
            # Arbitrary selection
            for p in pages:
                 new_doc.insert_pdf(self.doc, from_page=p, to_page=p)
        
        try:
            new_doc.save(output_path, garbage=garbage, deflate=deflate)
            log.info(f"Saved subset to {output_path} ({len(pages)} pages)")
        except Exception as exc:
            translate_save_error(exc, output_path)
            raise
        finally:
            new_doc.close()
    
    def close(self):
        """Close document"""
        if self.doc:
            self.doc.close()
            log.debug(f"Closed {self.filepath.name}")
        self._file_buffer = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    @staticmethod
    def merge_pdfs(pdf_paths: List[str], output_path: str):
        """
        Merge multiple PDFs into one
        
        Args:
            pdf_paths: List of PDF file paths to merge
            output_path: Output file path
        """
        result = fitz.open()
        
        for pdf_path in pdf_paths:
            with fitz.open(pdf_path) as pdf:
                result.insert_pdf(pdf)
        
        result.save(output_path)
        result.close()
        log.info(f"Merged {len(pdf_paths)} PDFs into {output_path}")
    
    @staticmethod
    def split_pdf(pdf_path: str, output_dir: str, pages_per_file: int = 10):
        """
        Split PDF into multiple files
        
        Args:
            pdf_path: Input PDF path
            output_dir: Output directory
            pages_per_file: Number of pages per output file
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with fitz.open(pdf_path) as doc:
            total_pages = len(doc)
            file_num = 1
            
            for start_page in range(0, total_pages, pages_per_file):
                end_page = min(start_page + pages_per_file, total_pages)
                
                # Create new PDF with subset of pages
                output_pdf = fitz.open()
                output_pdf.insert_pdf(doc, from_page=start_page, to_page=end_page-1)
                
                # Save
                output_file = output_dir / f"part_{file_num:03d}.pdf"
                output_pdf.save(str(output_file))
                output_pdf.close()
                
                log.info(f"Created {output_file.name} (pages {start_page+1}-{end_page})")
                file_num += 1
    
    def close(self):
        """Close the PDF document and free resources"""
        if self.doc:
            self.doc.close()
            log.debug(f"Closed PDF document: {self.filepath.name}")
