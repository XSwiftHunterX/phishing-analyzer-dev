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
    """
    Placeholder version for screenshot privacy scanning.

    Right now this does not perform OCR yet.
    It simply returns a neutral result so we can wire the pipeline in safely.

    Later this function will:
    1. extract text from the screenshot with OCR
    2. run detect_pii() on the extracted text
    3. return the combined result
    """

    if not image_field_file:
        return ScreenshotPrivacyResult(
            detected=False,
            status="approved",
            review_required=False,
            notes="",
            extracted_text=""
        )

    return ScreenshotPrivacyResult(
        detected=False,
        status="approved",
        review_required=False,
        notes="Screenshot uploaded. OCR privacy scan not yet enabled.",
        extracted_text=""
    )