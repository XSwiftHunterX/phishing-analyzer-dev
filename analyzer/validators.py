from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError
import os

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_IMAGE_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def validate_image(file):
    if not file:
        return

    if file.size > MAX_IMAGE_FILE_SIZE:
        raise ValidationError("Image file is too large. Maximum size is 5 MB.")

    content_type = getattr(file, "content_type", None)
    if content_type and not content_type.startswith("image/"):
        raise ValidationError("File must be an image.")

    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError("Only JPG, JPEG, PNG, and WEBP files are allowed.")

    try:
        file.seek(0)
        img = Image.open(file)
        img.verify()
    except UnidentifiedImageError:
        raise ValidationError("Invalid image file.")
    except OSError:
        raise ValidationError("Invalid image file.")

    try:
        file.seek(0)
        img = Image.open(file)

        if img.format not in ALLOWED_IMAGE_FORMATS:
            raise ValidationError("Only JPG, JPEG, PNG, and WEBP files are allowed.")

        if img.width > 5000 or img.height > 5000:
            raise ValidationError("Image too large (max 5000x5000).")
    except UnidentifiedImageError:
        raise ValidationError("Invalid image file.")
    except OSError:
        raise ValidationError("Invalid image file.")
    finally:
        file.seek(0)