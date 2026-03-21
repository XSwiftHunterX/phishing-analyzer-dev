from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


@dataclass
class ImageModerationResult:
    moderation_status: str
    moderation_reason: str
    moderation_labels: list[dict[str, Any]] = field(default_factory=list)

    relevance_status: str = "approved"
    relevance_reason: str = ""
    looks_like_message_screenshot: bool = True

    review_required: bool = False


MESSAGE_LIKE_LABELS = {
    "Electronics",
    "Computer",
    "Laptop",
    "Pc",
    "Monitor",
    "Screen",
    "Mobile Phone",
    "Cell Phone",
    "Phone",
    "Text",
    "Document",
    "Paper",
    "Website",
    "Web Page",
    "Advertisement",
    "Poster",
}

UNRELATED_HIGH_CONFIDENCE_LABELS = {
    "Person",
    "Face",
    "Selfie",
    "Portrait",
    "Dog",
    "Cat",
    "Pet",
    "Food",
    "Meal",
    "Drink",
    "Vehicle",
    "Car",
    "Truck",
    "Nature",
    "Mountain",
    "Beach",
    "Tree",
    "Flower",
    "Furniture",
    "Couch",
    "Bed",
}


def _get_rekognition_client():
    return boto3.client("rekognition")


def _read_image_bytes(image_field_file) -> bytes:
    image_field_file.file.seek(0)
    image_bytes = image_field_file.file.read()
    image_field_file.file.seek(0)
    return image_bytes


def _simplify_moderation_labels(raw_labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    simplified = []

    for label in raw_labels:
        simplified.append({
            "name": label.get("Name", ""),
            "parent_name": label.get("ParentName", ""),
            "confidence": round(label.get("Confidence", 0.0), 2),
            "taxonomy_level": label.get("TaxonomyLevel", 0),
        })

    return simplified


def _extract_label_names(label_response: dict) -> list[str]:
    names = []

    for label in label_response.get("Labels", []):
        name = label.get("Name")
        if name:
            names.append(name)

        for parent in label.get("Parents", []):
            parent_name = parent.get("Name")
            if parent_name:
                names.append(parent_name)

        for alias in label.get("Aliases", []):
            alias_name = alias.get("Name")
            if alias_name:
                names.append(alias_name)

        for category in label.get("Categories", []):
            category_name = category.get("Name")
            if category_name:
                names.append(category_name)

    return list(dict.fromkeys(names))


def _assess_relevance(label_names: list[str]) -> tuple[bool, str, str]:
    """
    Returns:
        looks_like_message_screenshot, relevance_status, relevance_reason
    """
    label_set = set(label_names)

    message_hits = sorted(label_set.intersection(MESSAGE_LIKE_LABELS))
    unrelated_hits = sorted(label_set.intersection(UNRELATED_HIGH_CONFIDENCE_LABELS))

    if message_hits:
        return (
            True,
            "approved",
            f"Image appears relevant to the platform. Detected screenshot/message-like labels: {', '.join(message_hits[:6])}."
        )

    if unrelated_hits:
        return (
            False,
            "pending",
            f"Image may be unrelated to a phishing or scam message. Detected labels: {', '.join(unrelated_hits[:6])}."
        )

    return (
        False,
        "pending",
        "Unable to confirm that the uploaded image is a phishing/message screenshot."
    )


def moderate_uploaded_image(image_field_file) -> ImageModerationResult:
    """
    Uses Amazon Rekognition to:
    1. detect unsafe/explicit visual content
    2. estimate whether the upload looks like a relevant phishing/message screenshot
    """
    if not image_field_file:
        return ImageModerationResult(
            moderation_status="approved",
            moderation_reason="",
            moderation_labels=[],
            relevance_status="approved",
            relevance_reason="No image uploaded.",
            looks_like_message_screenshot=True,
            review_required=False,
        )

    try:
        image_bytes = _read_image_bytes(image_field_file)
        client = _get_rekognition_client()

        moderation_response = client.detect_moderation_labels(
            Image={"Bytes": image_bytes},
            MinConfidence=70
        )
        moderation_labels = _simplify_moderation_labels(
            moderation_response.get("ModerationLabels", [])
        )

        label_response = client.detect_labels(
            Image={"Bytes": image_bytes},
            MaxLabels=20,
            MinConfidence=70
        )
        label_names = _extract_label_names(label_response)

        looks_like_message_screenshot, relevance_status, relevance_reason = _assess_relevance(label_names)

        if moderation_labels:
            top_labels = ", ".join(
                f"{label['name']} ({label['confidence']}%)"
                for label in moderation_labels[:5]
            )

            return ImageModerationResult(
                moderation_status="pending",
                moderation_reason=f"Possible unsafe image content detected: {top_labels}.",
                moderation_labels=moderation_labels,
                relevance_status=relevance_status,
                relevance_reason=relevance_reason,
                looks_like_message_screenshot=looks_like_message_screenshot,
                review_required=True,
            )

        if relevance_status == "pending":
            return ImageModerationResult(
                moderation_status="approved",
                moderation_reason="",
                moderation_labels=[],
                relevance_status=relevance_status,
                relevance_reason=relevance_reason,
                looks_like_message_screenshot=looks_like_message_screenshot,
                review_required=True,
            )

        return ImageModerationResult(
            moderation_status="approved",
            moderation_reason="",
            moderation_labels=[],
            relevance_status="approved",
            relevance_reason=relevance_reason,
            looks_like_message_screenshot=True,
            review_required=False,
        )

    except (BotoCoreError, ClientError) as exc:
        return ImageModerationResult(
            moderation_status="pending",
            moderation_reason=f"Image moderation failed: {exc}",
            moderation_labels=[],
            relevance_status="pending",
            relevance_reason="Could not verify whether the uploaded image is appropriate or relevant.",
            looks_like_message_screenshot=False,
            review_required=True,
        )