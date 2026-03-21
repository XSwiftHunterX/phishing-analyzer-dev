from dataclasses import dataclass
from .image_moderation import moderate_uploaded_image


@dataclass
class ProfileImageModerationResult:
    allowed: bool
    reason: str = ""


def moderate_profile_image(image_field_file) -> ProfileImageModerationResult:
    if not image_field_file:
        return ProfileImageModerationResult(
            allowed=True,
            reason=""
        )

    result = moderate_uploaded_image(image_field_file)

    # For profile pictures:
    # - ignore screenshot relevance
    # - block anything Rekognition thinks is inappropriate
    if result.moderation_status == "pending":
        return ProfileImageModerationResult(
            allowed=False,
            reason="That profile picture may contain inappropriate content. Please choose a different image."
        )

    return ProfileImageModerationResult(
        allowed=True,
        reason=""
    )