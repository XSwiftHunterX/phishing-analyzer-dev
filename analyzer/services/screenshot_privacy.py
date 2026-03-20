import pytesseract
from PIL import Image
from dataclasses import dataclass
from .pii_detection import detect_pii


@dataclass
class ScreenshotPrivacyResult:
    detected: bool
    status: str
    review_required: bool
    notes: str = ""
    extracted_text: str = ""


def scan_screenshot_for_pii(image_field_file) -> ScreenshotPrivacyResult:
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

        # Extract text from image
        extracted_text = pytesseract.image_to_string(image)

        # Run your existing PII detection
        pii_result = detect_pii(extracted_text, context="screenshot")

        return ScreenshotPrivacyResult(
            detected=pii_result.detected,
            status=pii_result.status,
            review_required=pii_result.review_required,
            notes=pii_result.notes,
            extracted_text=extracted_text[:500]  # limit stored preview
        )

    except Exception as e:
        return ScreenshotPrivacyResult(
            detected=False,
            status="approved",
            review_required=False,
            notes=f"OCR failed: {str(e)}",
            extracted_text=""
        )