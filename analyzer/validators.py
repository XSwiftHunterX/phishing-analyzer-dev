from django.core.exceptions import ValidationError
from PIL import Image

def validate_image(file):
    # Check MIME type
    if not file.content_type.startswith('image/'):
        raise ValidationError("File must be an image.")

    try:
        img = Image.open(file)
        img.verify()
    except Exception:
        raise ValidationError("Invalid image file.")

    file.seek(0)

    img = Image.open(file)

    # Limit dimensions
    if img.width > 5000 or img.height > 5000:
        raise ValidationError("Image too large (max 5000x5000).")