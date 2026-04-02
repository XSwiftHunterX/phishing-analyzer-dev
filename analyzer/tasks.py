import logging
from django_huey import task

from .models import Message
from .services.ai_analysis import analyze_message, save_analysis_result
from .services.image_moderation import moderate_uploaded_image
from .services.screenshot_privacy import scan_screenshot_for_pii

logger = logging.getLogger(__name__)


@task()
def test_background_task():
    logger.error("Huey test task ran successfully.")
    return "ok"


@task()
def run_ai_analysis_task(message_id):
    try:
        message = Message.objects.get(id=message_id)
        message.ai_status = "processing"
        message.save(update_fields=["ai_status"])

        analysis_data = analyze_message(message)
        save_analysis_result(message, analysis_data)

        message.ai_status = "completed"
        message.save(update_fields=["ai_status"])

        logger.info(f"AI analysis completed for message {message_id}")
    except Message.DoesNotExist:
        logger.error(f"AI task failed: message {message_id} does not exist")
    except Exception as e:
        try:
            message = Message.objects.get(id=message_id)
            message.ai_status = "failed"
            message.save(update_fields=["ai_status"])
        except Exception:
            pass
        logger.exception(f"AI task failed for message {message_id}: {e}")


@task()
def run_image_processing_task(message_id):
    try:
        message = Message.objects.get(id=message_id)
        message.image_processing_status = "processing"
        message.save(update_fields=["image_processing_status"])

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

    except Exception as e:
        try:
            message = Message.objects.get(id=message_id)
            message.image_processing_status = "failed"
            message.save(update_fields=["image_processing_status"])
        except Exception:
            pass
        logger.exception(f"Image processing failed for message {message_id}: {e}")