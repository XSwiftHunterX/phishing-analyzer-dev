import os
from io import BytesIO

from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image


OUTPUT_FORMAT_MAP = {
    "JPEG": "JPEG",
    "PNG": "PNG",
    "WEBP": "WEBP",
}

EXTENSION_MAP = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


def reencode_uploaded_image(uploaded_file):
    if not uploaded_file:
        return uploaded_file

    uploaded_file.seek(0)
    image = Image.open(uploaded_file)

    original_format = (image.format or "").upper()
    output_format = OUTPUT_FORMAT_MAP.get(original_format, "PNG")

    if output_format == "JPEG":
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")
    else:
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")

    output = BytesIO()
    image.save(output, format=output_format)
    output.seek(0)

    original_name = os.path.splitext(uploaded_file.name)[0]
    new_extension = EXTENSION_MAP[output_format]
    new_name = f"{original_name}{new_extension}"

    content_type = f"image/{output_format.lower()}"
    if output_format == "JPEG":
        content_type = "image/jpeg"

    return InMemoryUploadedFile(
        file=output,
        field_name=getattr(uploaded_file, "field_name", None),
        name=new_name,
        content_type=content_type,
        size=output.getbuffer().nbytes,
        charset=None,
    )