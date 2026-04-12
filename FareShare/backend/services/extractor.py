"""
Claude Vision extractor for county assessment notices.

Accepts PDF path or image path. Sends to Claude Sonnet with a structured
extraction prompt. Returns a typed dict with all parcel fields we need for
the comp analysis.
"""

import base64
import json
import re
from pathlib import Path
from typing import Optional

import anthropic
import pdfplumber

from config import settings


EXTRACTION_PROMPT = """You are an expert at reading Alabama county property tax assessment notices.

Extract the following fields from this assessment notice document. Return ONLY valid JSON — no markdown, no commentary.

Fields to extract:
{
  "parcel_id": "string — the parcel/account/map number",
  "county": "string — Alabama county name",
  "owner_name": "string — property owner name",
  "property_address": "string — property street address if visible",
  "property_class": "string — e.g. Class I Residential, Class II Agricultural, Class III Commercial, etc.",
  "land_use_code": "string — numeric or alpha land use code if present",
  "acreage": number or null,
  "appraised_value": number or null,
  "assessed_value": number or null,
  "tax_year": integer or null,
  "homestead_exempt": boolean,
  "current_use_enrolled": boolean,
  "legal_description": "string — lot/block/section description if present",
  "assessment_date": "string — date of assessment or notice"
}

Rules:
- For monetary values, return raw numbers with no $ or commas (e.g. 125000 not $125,000)
- For acreage, return decimal number (e.g. 42.5)
- If a field is not visible or not applicable, return null
- assessed_value in Alabama is typically 10-20% of appraised_value depending on class
- current_use_enrolled: true if you see "Current Use", "Use Value", "Agricultural Use" notations
- homestead_exempt: true if you see "Homestead" exemption listed
"""


def _pdf_to_images_base64(pdf_path: str) -> list[dict]:
    """
    Extract pages from PDF as base64-encoded images for Claude Vision.
    Returns list of image content blocks.
    """
    import pypdf
    from PIL import Image
    import io

    # Try text extraction first — faster and cheaper than vision
    text_content = _extract_pdf_text(pdf_path)
    if text_content and len(text_content.strip()) > 100:
        return [{"type": "text", "text": text_content}]

    # Fall back to page-as-image via pypdf + PIL
    reader = pypdf.PdfReader(pdf_path)
    content_blocks = []
    for page_num in range(min(len(reader.pages), 3)):  # cap at 3 pages
        page = reader.pages[page_num]
        # Render page to image via pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            if page_num < len(pdf.pages):
                img = pdf.pages[page_num].to_image(resolution=150)
                buf = io.BytesIO()
                img.original.save(buf, format="PNG")
                b64 = base64.standard_b64encode(buf.getvalue()).decode()
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                })
    return content_blocks


def _extract_pdf_text(pdf_path: str) -> str:
    """Extract text from PDF using pdfplumber."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:3]:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n\n".join(text_parts)


def _image_to_base64_block(image_path: str) -> dict:
    """Convert image file to Claude content block."""
    path = Path(image_path)
    suffix = path.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(suffix, "image/jpeg")
    with open(image_path, "rb") as f:
        b64 = base64.standard_b64encode(f.read()).decode()
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": b64},
    }


def extract_assessment(file_path: str) -> dict:
    """
    Main extraction function. Accepts PDF or image path.
    Returns structured dict of parcel fields.
    """
    path = Path(file_path)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    if path.suffix.lower() == ".pdf":
        content_blocks = _pdf_to_images_base64(file_path)
    else:
        content_blocks = [_image_to_base64_block(file_path)]

    content_blocks.append({"type": "text", "text": EXTRACTION_PROMPT})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": content_blocks}],
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown code fences if Claude adds them
    raw_text = re.sub(r"^```json\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    parsed = json.loads(raw_text)
    parsed["_raw_response"] = raw_text
    return parsed
