from .pii_detection import detect_pii
from .text_moderation import moderate_text
from ..models import ModerationStatus
from django.conf import settings


def queue_message_processing(message):
    from ..tasks import (
        run_ai_analysis_task,
        run_image_processing_task,
        check_message_processing_timeout_task,
    )

    run_ai_analysis_task(message.id)
    run_image_processing_task(message.id)
    check_message_processing_timeout_task.schedule(
        args=(message.id,),
        delay=getattr(settings, "MESSAGE_PROCESSING_TIMEOUT_SECONDS", 180)
    )

def apply_text_only_message_moderation(message, form):
    field_results = [
        getattr(form, '_message_content_moderation', None),
        getattr(form, '_sender_moderation', None),
        getattr(form, '_platform_moderation', None),
        getattr(form, '_additional_details_moderation', None),
    ]
    field_results = [result for result in field_results if result is not None]

    overall_status = ModerationStatus.APPROVED
    overall_reason_parts = []

    for result in field_results:
        if result.reason:
            overall_reason_parts.append(result.reason)

        if result.status == "rejected":
            overall_status = ModerationStatus.REJECTED
        elif result.status == "pending" and overall_status != ModerationStatus.REJECTED:
            overall_status = ModerationStatus.PENDING

    pii_results = [
        detect_pii(message.message_content, context="message_content", sender=message.sender),
        detect_pii(message.sender, context="sender", sender=message.sender),
        detect_pii(message.platform, context="platform", sender=message.sender),
        detect_pii(message.additional_details, context="additional_details", sender=message.sender),
    ]

    pii_detected = any(result.detected for result in pii_results)
    pii_review_required = any(result.review_required for result in pii_results)

    pii_status = ModerationStatus.APPROVED
    pii_notes_parts = []

    for result in pii_results:
        if result.notes:
            pii_notes_parts.append(result.notes)

        if result.status == "rejected":
            pii_status = ModerationStatus.REJECTED
        elif result.status == "pending" and pii_status != ModerationStatus.REJECTED:
            pii_status = ModerationStatus.PENDING

    message.pii_detected = pii_detected
    message.pii_review_required = pii_review_required
    message.pii_scan_status = pii_status
    message.pii_notes = " | ".join(pii_notes_parts)

    if pii_status == ModerationStatus.REJECTED:
        overall_status = ModerationStatus.REJECTED
    elif pii_status == ModerationStatus.PENDING and overall_status != ModerationStatus.REJECTED:
        overall_status = ModerationStatus.PENDING

    all_reasons = []
    all_reasons.extend(overall_reason_parts)
    all_reasons.extend(pii_notes_parts)

    message.moderation_status = overall_status
    message.moderation_reason = (
        "\n• " + "\n• ".join(all_reasons)
        if all_reasons else ""
    )

    return message


def apply_async_image_results_to_overall_moderation(message):
    image_reason_parts = []

    overall_status = message.moderation_status or ModerationStatus.APPROVED

    if message.image_moderation_reason:
        image_reason_parts.append(message.image_moderation_reason)

    if message.image_relevance_reason:
        image_reason_parts.append(message.image_relevance_reason)

    if message.image_moderation_status == ModerationStatus.REJECTED:
        overall_status = ModerationStatus.REJECTED
    elif (
        message.image_moderation_status == ModerationStatus.PENDING
        and overall_status != ModerationStatus.REJECTED
    ):
        overall_status = ModerationStatus.PENDING

    if message.image_relevance_status == ModerationStatus.REJECTED:
        overall_status = ModerationStatus.REJECTED
    elif (
        message.image_relevance_status == ModerationStatus.PENDING
        and overall_status != ModerationStatus.REJECTED
    ):
        overall_status = ModerationStatus.PENDING

    if message.pii_scan_status == ModerationStatus.REJECTED:
        overall_status = ModerationStatus.REJECTED
    elif (
        message.pii_scan_status == ModerationStatus.PENDING
        and overall_status != ModerationStatus.REJECTED
    ):
        overall_status = ModerationStatus.PENDING

    existing_reason = (message.moderation_reason or "").strip()
    extra_reasons = []

    if image_reason_parts:
        extra_reasons.extend(image_reason_parts)

    if extra_reasons:
        extra_reason_text = "\n• " + "\n• ".join(extra_reasons)
        if existing_reason:
            message.moderation_reason = existing_reason + extra_reason_text
        else:
            message.moderation_reason = extra_reason_text
    else:
        message.moderation_reason = existing_reason

    message.moderation_status = overall_status
    return message


def populate_text_moderation_results(form, message):
    content = message.message_content or ""
    sender = message.sender or ""
    platform = message.platform or ""
    details = message.additional_details or ""

    form.cleaned_data = {
        'message_content': content,
        'sender': sender,
        'platform': platform,
        'additional_details': details,
    }

    form._message_content_moderation = moderate_text(content, context="message_content")
    form._sender_moderation = moderate_text(sender, context="sender")
    form._platform_moderation = moderate_text(platform, context="platform")
    form._additional_details_moderation = moderate_text(details, context="additional_details")

    return form


def reset_message_processing_state(message):
    message.processing_status = "pending"
    message.processing_error = ""
    message.processing_failure_type = ""
    message.is_finalized = False
    message.ai_status = "pending"
    message.image_processing_status = "pending"
    message.processing_completed_at = None
    return message