"""Gemini Vision pipeline for image understanding.

Uses Gemini Vision API (free tier) for:
- Single & multi-image understanding
- Chart/graph interpretation
- OCR from images
- PDF page image analysis (lazy, on-demand)
"""

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore
    genai_types = None  # type: ignore

_vision_client = None

MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _get_client():
    global _vision_client
    if _vision_client is None:
        if genai is None:
            raise RuntimeError("google-genai is required for vision. Run: pip install google-genai")

        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required for vision features.")
        _vision_client = genai.Client(api_key=api_key)
    return _vision_client


def understand_image(
    image_bytes: bytes,
    query: str = "Describe this image in detail.",
    mime_type: str = "image/png",
) -> str:
    """Send a single image to Gemini Vision for understanding."""
    client = _get_client()
    image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[query, image_part],
    )
    return response.text or "(No response from vision model)"


def understand_multiple_images(
    image_files: list[Path],
    query: str = "Describe these images in detail.",
) -> str:
    """Send MULTIPLE images to Gemini Vision in a single request.

    Gemini supports multi-image understanding natively.
    Each image is labeled (Image 1, Image 2, ...) for reference.
    """
    client = _get_client()

    # Build content parts: text query + all images
    parts: list[Any] = []

    # Add labeled instruction
    file_labels = "\n".join(
        f"- Image {i+1}: {f.name}" for i, f in enumerate(image_files)
    )
    full_query = f"""{query}

The following {len(image_files)} images are provided:
{file_labels}

Analyze ALL images. Reference them as "Image 1", "Image 2", etc. when discussing each one."""
    parts.append(full_query)

    # Add each image as a part
    for filepath in image_files:
        mime_type = MIME_MAP.get(filepath.suffix.lower(), "image/png")
        image_bytes = filepath.read_bytes()
        parts.append(
            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=parts,
    )
    return response.text or "(No response from vision model)"


def understand_image_from_file(filepath: Path, query: str = "Describe this image in detail.") -> str:
    """Load an image from disk and send to Gemini Vision."""
    mime_type = MIME_MAP.get(filepath.suffix.lower(), "image/png")
    image_bytes = filepath.read_bytes()
    return understand_image(image_bytes, query=query, mime_type=mime_type)


def understand_pdf_page(pdf_path: Path, page_num: int, query: str) -> str:
    """Extract a specific page from a PDF as an image and analyze it with Gemini Vision."""
    from app.pdf_processor import extract_page_image
    image_bytes = extract_page_image(pdf_path, page_num, dpi=150)
    return understand_image(image_bytes, query=query, mime_type="image/png")


def get_image_summary(filepath: Path) -> str:
    """Quick one-line summary of an image for chat context."""
    try:
        return understand_image_from_file(
            filepath,
            query="Provide a brief one-sentence description of what this image contains."
        )
    except Exception as e:
        logger.error("Image summary failed: %s", e)
        return f"Image file: {filepath.name}"


def detect_image_intent(query: str) -> bool:
    """Heuristic to detect if a query is about visual content."""
    image_keywords = [
        "image", "picture", "photo", "screenshot", "diagram",
        "chart", "graph", "figure", "table", "visual",
        "show me", "what does", "describe the", "explain the",
        "ocr", "read the text", "what's in",
    ]
    query_lower = query.lower()
    return any(kw in query_lower for kw in image_keywords)
