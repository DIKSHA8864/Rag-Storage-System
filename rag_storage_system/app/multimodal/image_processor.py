"""
Image processing for Client intake - runs the configured OCR provider
(app/multimodal/ocr.py) to pull out any printed/handwritten text, plus
the configured Vision provider (app/multimodal/vision.py) for a short
description of the image's visual content. Both run on every image;
either result may be mock but is never fabricated as if it were the
other's.
"""

from app.multimodal.models import ExtractedContent
from app.multimodal.ocr import get_ocr_provider
from app.multimodal.vision import get_vision_provider


def process_image(filename: str, data: bytes) -> list[ExtractedContent]:
    ocr_provider = get_ocr_provider()
    vision_provider = get_vision_provider()

    ocr_text, ocr_is_mock = ocr_provider.extract_text(data, filename)
    caption, caption_is_mock = vision_provider.describe(data, filename)

    return [
        ExtractedContent(content_type="ocr_text", text=ocr_text, provider=ocr_provider.name, is_mock=ocr_is_mock),
        ExtractedContent(content_type="caption", text=caption, provider=vision_provider.name, is_mock=caption_is_mock),
    ]
