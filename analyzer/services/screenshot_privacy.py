import io
import os
import re
import uuid
import pytesseract

from PIL import Image, ImageDraw
from dataclasses import dataclass
from django.core.files.base import ContentFile
from .pii_detection import detect_pii, normalize_email, normalize_phone


@dataclass
class ScreenshotPrivacyResult:
    detected: bool
    status: str
    review_required: bool
    notes: str = ""
    extracted_text: str = ""
    redacted_image_content: ContentFile | None = None
    redacted_image_name: str = ""


def normalize_ocr_token(token: str) -> str:
    return token.strip()


def token_matches_pii(token: str, pii_match) -> bool:
    token = normalize_ocr_token(token)
    if not token:
        return False

    if pii_match.entity_type == "email":
        return normalize_email(token) == normalize_email(pii_match.value)

    if pii_match.entity_type == "phone":
        return normalize_phone(token) == normalize_phone(pii_match.value)

    if pii_match.entity_type == "ssn":
        return token == pii_match.value

    if pii_match.entity_type == "card":
        token_digits = re.sub(r"\D", "", token)
        match_digits = re.sub(r"\D", "", pii_match.value)
        return token_digits == match_digits

    return False


def line_contains_pii(line_text: str, pii_match) -> bool:
    if not line_text.strip():
        return False

    if pii_match.entity_type == "email":
        return normalize_email(pii_match.value) in normalize_email(line_text)

    if pii_match.entity_type == "phone":
        line_digits = normalize_phone(line_text)
        match_digits = normalize_phone(pii_match.value)
        return bool(line_digits and match_digits and match_digits in line_digits)

    if pii_match.entity_type == "ssn":
        return pii_match.value in line_text

    if pii_match.entity_type == "card":
        line_digits = re.sub(r"\D", "", line_text)
        match_digits = re.sub(r"\D", "", pii_match.value)
        return bool(line_digits and match_digits and match_digits in line_digits)

    return False


def get_matching_boxes(ocr_data: dict, pii_matches: list) -> list[tuple[int, int, int, int]]:
    boxes = []
    n = len(ocr_data["text"])

    for i in range(n):
        word = (ocr_data["text"][i] or "").strip()
        if not word:
            continue

        left = int(ocr_data["left"][i])
        top = int(ocr_data["top"][i])
        width = int(ocr_data["width"][i])
        height = int(ocr_data["height"][i])

        for pii_match in pii_matches:
            if token_matches_pii(word, pii_match):
                boxes.append((left, top, left + width, top + height))
                break

    # fallback: line-level matching for multi-token phone/card patterns
    line_groups = {}
    for i in range(n):
        word = (ocr_data["text"][i] or "").strip()
        if not word:
            continue

        block_num = ocr_data["block_num"][i]
        par_num = ocr_data["par_num"][i]
        line_num = ocr_data["line_num"][i]
        key = (block_num, par_num, line_num)
        line_groups.setdefault(key, []).append(i)

    for indices in line_groups.values():
        line_words = [(ocr_data["text"][i] or "").strip() for i in indices]
        line_text = " ".join(w for w in line_words if w)

        for pii_match in pii_matches:
            if line_contains_pii(line_text, pii_match):
                lefts = [int(ocr_data["left"][i]) for i in indices]
                tops = [int(ocr_data["top"][i]) for i in indices]
                rights = [int(ocr_data["left"][i]) + int(ocr_data["width"][i]) for i in indices]
                bottoms = [int(ocr_data["top"][i]) + int(ocr_data["height"][i]) for i in indices]
                boxes.append((min(lefts), min(tops), max(rights), max(bottoms)))
                break

    return deduplicate_boxes(boxes)


def deduplicate_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    unique = []
    seen = set()

    for box in boxes:
        if box not in seen:
            seen.add(box)
            unique.append(box)

    return unique


def redact_image(image: Image.Image, boxes: list[tuple[int, int, int, int]]) -> ContentFile | None:
    if not boxes:
        return None

    redacted = image.copy()
    draw = ImageDraw.Draw(redacted)

    for left, top, right, bottom in boxes:
        padding = 3
        draw.rectangle(
            (left - padding, top - padding, right + padding, bottom + padding),
            fill="black"
        )

    output = io.BytesIO()
    save_format = redacted.format if redacted.format in {"PNG", "JPEG"} else "PNG"
    redacted.save(output, format=save_format)
    output.seek(0)

    ext = ".png" if save_format == "PNG" else ".jpg"
    filename = f"redacted_{uuid.uuid4().hex}{ext}"

    return ContentFile(output.read(), name=filename)


def scan_screenshot_for_pii(image_field_file, sender: str | None = None) -> ScreenshotPrivacyResult:
    if not image_field_file:
        return ScreenshotPrivacyResult(
            detected=False,
            status="approved",
            review_required=False,
            notes="",
            extracted_text=""
        )

    try:
        image = Image.open(image_field_file.file)
        image.load()

        extracted_text = pytesseract.image_to_string(image)

        pii_result = detect_pii(
            extracted_text,
            context="screenshot",
            sender=sender
        )

        redacted_file = None
        redacted_name = ""

        if pii_result.matches:
            ocr_data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT
            )
            boxes = get_matching_boxes(ocr_data, pii_result.matches)
            redacted_file = redact_image(image, boxes)
            if redacted_file:
                redacted_name = redacted_file.name

        return ScreenshotPrivacyResult(
            detected=pii_result.detected,
            status=pii_result.status,
            review_required=pii_result.review_required,
            notes=pii_result.notes,
            extracted_text=extracted_text[:500],
            redacted_image_content=redacted_file,
            redacted_image_name=redacted_name
        )

    except Exception as e:
        return ScreenshotPrivacyResult(
            detected=False,
            status="approved",
            review_required=False,
            notes=f"OCR failed: {str(e)}",
            extracted_text=""
        )