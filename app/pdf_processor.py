"""PDF text extraction with OCR fallback for scanned pages.

Pipeline:
1. Extract text with PyMuPDF (fast, native)
2. Detect pages with < 50 chars → likely scanned / image-heavy
3. OCR only those failed pages with EasyOCR
4. Extract image references (lazy — metadata only, not pixel data)
"""

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore

# EasyOCR is imported lazily to keep startup fast
_ocr_reader = None

MIN_CHARS_PER_PAGE = 50  # below this, we assume the page is scanned


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        except ImportError:
            logger.warning("easyocr is not installed — OCR will be unavailable")
            return None
    return _ocr_reader


def _doc_id(filepath: Path) -> str:
    """Generate a deterministic doc ID from filename + size."""
    stat = filepath.stat()
    raw = f"{filepath.name}:{stat.st_size}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def extract_text_from_pdf(filepath: Path) -> dict[str, Any]:
    """Extract text from a PDF file.

    Returns:
        {
            "doc_id": str,
            "filename": str,
            "pages": [
                {"page": 1, "text": "...", "method": "pymupdf"|"ocr", "has_images": bool},
                ...
            ],
            "total_pages": int,
            "image_pages": [int, ...],  # pages that contain images
        }
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is not installed. Run: pip install PyMuPDF")

    doc = fitz.open(str(filepath))
    doc_id = _doc_id(filepath)
    pages: list[dict[str, Any]] = []
    image_pages: list[int] = []
    failed_pages: list[int] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text").strip()
        has_images = len(page.get_images(full=True)) > 0

        if has_images:
            image_pages.append(page_num + 1)

        if len(text) >= MIN_CHARS_PER_PAGE:
            pages.append({
                "page": page_num + 1,
                "text": text,
                "method": "pymupdf",
                "has_images": has_images,
            })
        else:
            failed_pages.append(page_num)
            pages.append({
                "page": page_num + 1,
                "text": text,
                "method": "pending_ocr",
                "has_images": has_images,
            })

    # OCR failed pages
    if failed_pages:
        reader = _get_ocr_reader()
        if reader is not None:
            for page_num in failed_pages:
                page = doc[page_num]
                # Render page to image for OCR
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")

                import io
                from PIL import Image
                img = Image.open(io.BytesIO(img_bytes))
                import numpy as np
                img_array = np.array(img)

                results = reader.readtext(img_array, detail=0)
                ocr_text = "\n".join(results).strip()

                # Update the page entry
                for p in pages:
                    if p["page"] == page_num + 1:
                        p["text"] = ocr_text if ocr_text else p["text"]
                        p["method"] = "ocr" if ocr_text else "empty"
                        break

    doc.close()

    return {
        "doc_id": doc_id,
        "filename": filepath.name,
        "pages": pages,
        "total_pages": len(pages),
        "image_pages": image_pages,
    }


def extract_page_image(filepath: Path, page_num: int, dpi: int = 150) -> bytes:
    """Extract a single page as a PNG image (for Gemini Vision).

    Args:
        filepath: Path to the PDF
        page_num: 1-indexed page number
        dpi: Resolution for rendering

    Returns:
        PNG image bytes
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed")

    doc = fitz.open(str(filepath))
    page = doc[page_num - 1]
    pix = page.get_pixmap(dpi=dpi)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def get_pdf_metadata(filepath: Path) -> dict[str, Any]:
    """Get basic PDF metadata without full extraction."""
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed")

    doc = fitz.open(str(filepath))
    meta = {
        "filename": filepath.name,
        "page_count": len(doc),
        "metadata": doc.metadata,
        "file_size_bytes": filepath.stat().st_size,
    }
    doc.close()
    return meta
