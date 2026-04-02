from django.core.exceptions import ValidationError
from PIL import Image

def validate_image(file):
    content_type = getattr(file, "content_type", None)
    if content_type and not content_type.startswith("image/"):
        raise ValidationError("File must be an image.")

    try:
        img = Image.open(file)
        img.verify()
    except Exception:
        raise ValidationError("Invalid image file.")

    file.seek(0)

    try:
        img = Image.open(file)
        if img.width > 5000 or img.height > 5000:
            raise ValidationError("Image too large (max 5000x5000).")
    except Exception:
        raise ValidationError("Invalid image file.")

    file.seek(0)