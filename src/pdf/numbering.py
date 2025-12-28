"""
PDF Page Numbering Module
Adds page numbers to PDF documents using PyMuPDF
"""
import logging
import fitz  # PyMuPDF
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)


class PdfNumbering:
    """Handle PDF page numbering operations"""
    
    def __init__(self):
        self.default_font = "helv"  # Helvetica
        self.default_fontsize = 11
        self.default_color = (0, 0, 0)  # Black
    
    def add_page_numbers(
        self,
        input_path: str,
        output_path: str,
        format_string: str = "Página %(n) de %(N)",
        position: str = "bottom-center",
        font: str = None,
        fontsize: int = None,
        color: Tuple[float, float, float] = None,
        margin: int = 30
    ) -> bool:
        """
        Add page numbers to a PDF document
        
        Args:
            input_path: Path to input PDF
            output_path: Path to save numbered PDF
            format_string: Format for page numbers. %(n) = current page, %(N) = total pages
            position: Position of numbers (bottom-center, bottom-left, bottom-right, etc.)
            font: Font name (helv, times, cour)
            fontsize: Font size in points
            color: RGB color tuple (0-1 range)
            margin: Margin from edge in points
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Open PDF
            doc = fitz.open(input_path)
            total_pages = len(doc)
            
            # Use defaults if not specified
            font = font or self.default_font
            fontsize = fontsize or self.default_fontsize
            color = color or self.default_color
            
            log.info(f"Adding page numbers to {total_pages} pages")
            
            # Process each page
            for page_num in range(total_pages):
                page = doc[page_num]
                
                # Format the page number text
                text = format_string.replace("%(n)", str(page_num + 1))
                text = text.replace("%(N)", str(total_pages))
                
                # Get page dimensions
                rect = page.rect
                page_width = rect.width
                page_height = rect.height
                
                # Calculate text position based on position parameter
                x, y = self._calculate_position(
                    position, page_width, page_height, margin, fontsize
                )
                
                # Adjust x position for centered text
                if "center" in position:
                    # Get text width to center it
                    text_width = fitz.get_text_length(text, fontname=font, fontsize=fontsize)
                    x = x - (text_width / 2)
                
                # Insert text
                page.insert_text(
                    (x, y),
                    text,
                    fontname=font,
                    fontsize=fontsize,
                    color=color
                )
                
                log.debug(f"Added number to page {page_num + 1}: '{text}'")
            
            # Save the modified PDF
            doc.save(output_path)
            doc.close()
            
            log.info(f"Numbered PDF saved to: {output_path}")
            return True
            
        except Exception as e:
            log.error(f"Error adding page numbers: {e}", exc_info=True)
            return False
    
    def _calculate_position(
        self,
        position: str,
        page_width: float,
        page_height: float,
        margin: int,
        fontsize: int
    ) -> Tuple[float, float]:
        """
        Calculate x, y coordinates for text based on position string
        
        Args:
            position: Position string (e.g., "bottom-center")
            page_width: Width of page in points
            page_height: Height of page in points
            margin: Margin from edge in points
            fontsize: Font size in points
            
        Returns:
            Tuple of (x, y) coordinates
        """
        # Vertical position
        if "top" in position:
            y = margin + fontsize
        elif "bottom" in position:
            y = page_height - margin + 17  # User requested 17px lower
        else:  # middle
            y = page_height / 2
        
        # Horizontal position
        if "left" in position:
            x = margin
        elif "right" in position:
            x = page_width - margin
        else:  # center
            x = page_width / 2
        
        return (x, y)
    
    def add_page_numbers_to_selection(
        self,
        input_path: str,
        output_path: str,
        page_indices: list,
        format_string: str = "Página %(n) de %(N)",
        **kwargs
    ) -> bool:
        """
        Add page numbers only to selected pages
        
        Args:
            input_path: Path to input PDF
            output_path: Path to save numbered PDF
            page_indices: List of page indices (0-based) to number
            format_string: Format for page numbers
            **kwargs: Additional arguments passed to add_page_numbers
            
        Returns:
            True if successful, False otherwise
        """
        try:
            doc = fitz.open(input_path)
            total_pages = len(doc)
            
            # Get parameters
            font = kwargs.get('font', self.default_font)
            fontsize = kwargs.get('fontsize', self.default_fontsize)
            color = kwargs.get('color', self.default_color)
            margin = kwargs.get('margin', 30)
            position = kwargs.get('position', 'bottom-center')
            
            log.info(f"Adding page numbers to {len(page_indices)} selected pages")
            
            # Process only selected pages
            for page_num in page_indices:
                if page_num < 0 or page_num >= total_pages:
                    log.warning(f"Skipping invalid page index: {page_num}")
                    continue
                
                page = doc[page_num]
                
                # Format the page number text
                text = format_string.replace("%(n)", str(page_num + 1))
                text = text.replace("%(N)", str(total_pages))
                
                # Get page dimensions
                rect = page.rect
                page_width = rect.width
                page_height = rect.height
                
                # Calculate text position
                x, y = self._calculate_position(
                    position, page_width, page_height, margin, fontsize
                )
                
                # Adjust x position for centered text
                if "center" in position:
                    # Get text width to center it
                    text_width = fitz.get_text_length(text, fontname=font, fontsize=fontsize)
                    x = x - (text_width / 2)
                
                # Insert text
                page.insert_text(
                    (x, y),
                    text,
                    fontname=font,
                    fontsize=fontsize,
                    color=color
                )
                
                log.debug(f"Added number to page {page_num + 1}: '{text}'")
            
            # Save the modified PDF
            doc.save(output_path)
            doc.close()
            
            log.info(f"Numbered PDF saved to: {output_path}")
            return True
            
        except Exception as e:
            log.error(f"Error adding page numbers to selection: {e}", exc_info=True)
            return False
