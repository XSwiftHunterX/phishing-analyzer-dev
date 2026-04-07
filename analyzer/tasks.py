import logging

from django.utils import timezone
from django_huey import task

from .forms import MessageForm
from .models import Message, ModerationStatus
from .services.ai_analysis import analyze_message, save_analysis_result
from .services.image_moderation import moderate_uploaded_image
from .services.screenshot_privacy import scan_screenshot_for_pii
from .services.message_processing import (
    apply_text_only_message_moderation,
    apply_async_image_results_to_overall_moderation,
    populate_text_moderation_results,
)
from django.conf import settings
from datetime import timedelta
from django.db import transaction

logger = logging.getLogger(__name__)

def mark_message_processing_failed(message, error_text, failure_type):
    message.processing_status = "failed"
    message.processing_error = error_text
    message.processing_failure_type = failure_type
    message.save(update_fields=["processing_status", "processing_error", "processing_failure_type"])

@task()
def check_message_processing_timeout_task(message_id):
    try:
        logger.info("Timeout check started for message %s", message_id)
        message = Message.objects.get(id=message_id)

        if message.is_finalized or message.processing_status == "completed":
            logger.info(
                "Timeout check skipped for message %s because it is already done",
                message_id
            )
            return

        timeout_seconds = getattr(settings, "MESSAGE_PROCESSING_TIMEOUT_SECONDS", 180)
        deadline = message.processing_started_at + timedelta(seconds=timeout_seconds)

        if timezone.now() >= deadline:
            mark_message_processing_failed(
                message,
                "Processing took too long and timed out. Please try submitting again.",
                "timeout_failure",
            )
            logger.warning("Message %s timed out during processing", message_id)
        else:
            logger.info("Timeout check passed for message %s; not timed out yet", message_id)

    except Message.DoesNotExist:
        logger.error("Timeout check failed: message %s does not exist", message_id)
    except Exception:
        logger.exception("Timeout check failed for message %s", message_id)

def maybe_queue_finalize(message_id):
    message = Message.objects.get(id=message_id)

    if (
        message.ai_status == "completed"
        and message.image_processing_status == "completed"
        and not message.is_finalized
        and message.processing_status != "failed"
    ):
        logger.info("Finalize queued for message %s", message_id)
        finalize_message_task(message.id)
    else:
        logger.info(
            "Finalize not queued for message %s (ai_status=%s, image_processing_status=%s, is_finalized=%s, processing_status=%s)",
            message_id,
            message.ai_status,
            message.image_processing_status,
            message.is_finalized,
            message.processing_status,
        )


@task()
def test_background_task():
    logger.error("Huey test task ran successfully.")
    return "ok"


@task()
def run_ai_analysis_task(message_id):
    try:
        logger.info("AI analysis started for message %s", message_id)
        message = Message.objects.get(id=message_id)
        if message.is_finalized or message.processing_status in {"completed", "failed"}:
            logger.info(
                "AI analysis skipped for message %s because processing is already %s",
                message_id,
                message.processing_status,
            )
            return
        message.ai_status = "processing"
        message.processing_status = "processing"
        message.save(update_fields=["ai_status", "processing_status"])

        analysis_data = analyze_message(message)
        save_analysis_result(message, analysis_data)

        message.ai_status = "completed"
        message.save(update_fields=["ai_status"])

        maybe_queue_finalize(message_id)

        logger.info(f"AI analysis completed for message {message_id}")
    except Message.DoesNotExist:
        logger.error(f"AI task failed: message {message_id} does not exist")
    except Exception as e:
        try:
            message = Message.objects.get(id=message_id)
            message.ai_status = "failed"
            message.processing_status = "failed"
            message.processing_error = f"AI analysis failed: {e}"
            message.processing_failure_type = "ai_failure"
            message.save(update_fields=["ai_status", "processing_status", "processing_error", "processing_failure_type"])
        except Exception:
            pass
        logger.exception(f"AI task failed for message {message_id}: {e}")


@task()
def run_image_processing_task(message_id):
    try:
        logger.info("Image processing started for message %s", message_id)
        message = Message.objects.get(id=message_id)
        if message.is_finalized or message.processing_status in {"completed", "failed"}:
            logger.info(
                "Image processing skipped for message %s because processing is already %s",
                message_id,
                message.processing_status,
            )
            return
        message.image_processing_status = "processing"
        message.processing_status = "processing"
        message.save(update_fields=["image_processing_status", "processing_status"])

        if message.screenshot:
            image_mod_result = moderate_uploaded_image(message.screenshot)

            message.image_moderation_status = image_mod_result.moderation_status
            message.image_moderation_reason = image_mod_result.moderation_reason
            message.image_moderation_labels = image_mod_result.moderation_labels

            message.image_relevance_status = image_mod_result.relevance_status
            message.image_relevance_reason = image_mod_result.relevance_reason

            screenshot_result = scan_screenshot_for_pii(
                message.screenshot,
                sender=message.sender
            )

            if screenshot_result.redacted_image_content:
                message.redacted_screenshot.save(
                    screenshot_result.redacted_image_name,
                    screenshot_result.redacted_image_content,
                    save=False
                )
            else:
                message.redacted_screenshot = None

            if screenshot_result.detected:
                message.pii_detected = True

            if screenshot_result.notes:
                if message.pii_notes:
                    message.pii_notes += " | " + screenshot_result.notes
                else:
                    message.pii_notes = screenshot_result.notes

        else:
            message.redacted_screenshot = None
            message.image_moderation_status = "approved"
            message.image_moderation_reason = ""
            message.image_moderation_labels = []
            message.image_relevance_status = "approved"
            message.image_relevance_reason = ""

        message.image_processing_status = "completed"
        message.save()

        maybe_queue_finalize(message_id)

    except Exception as e:
        try:
            message = Message.objects.get(id=message_id)
            message.image_processing_status = "failed"
            message.processing_status = "failed"
            message.processing_error = f"Image processing failed: {e}"
            message.processing_failure_type = "image_failure"
            message.save(update_fields=["image_processing_status", "processing_status", "processing_error", "processing_failure_type"])
        except Exception:
            pass
        logger.exception(f"Image processing failed for message {message_id}: {e}")


@task()
def finalize_message_task(message_id):
    try:
        logger.info("Finalization started for message %s", message_id)
        with transaction.atomic():
            message = Message.objects.select_for_update().get(id=message_id)

            if message.is_finalized:
                logger.info("Finalization skipped for message %s because it was already finalized", message_id)
                return

            form = MessageForm(instance=message)
            form = populate_text_moderation_results(form, message)

            message = apply_text_only_message_moderation(message, form)
            message = apply_async_image_results_to_overall_moderation(message)

            if message.duplicate_submission_suspected:
                message.moderation_status = ModerationStatus.PENDING

                duplicate_reason = "Possible duplicate submission in a short time."
                existing_reason = (message.moderation_reason or "").strip()

                if duplicate_reason not in existing_reason:
                    if existing_reason:
                        message.moderation_reason = existing_reason + "\n• " + duplicate_reason
                    else:
                        message.moderation_reason = duplicate_reason

            message.processing_status = "completed"
            message.is_finalized = True
            message.processing_error = ""
            message.processing_failure_type = ""
            message.processing_completed_at = timezone.now()
            message.save()

        logger.info(f"Finalization completed for message {message_id}")

    except Message.DoesNotExist:
        logger.error(f"Finalize task failed: message {message_id} does not exist")
    except Exception as e:
        try:
            message = Message.objects.get(id=message_id)
            message.processing_status = "failed"
            message.processing_error = f"Finalization failed: {e}"
            message.processing_failure_type = "finalization_failure"
            message.save(update_fields=["processing_status", "processing_error", "processing_failure_type"])
        except Exception:
            pass
        logger.exception(f"Finalization failed for message {message_id}: {e}")