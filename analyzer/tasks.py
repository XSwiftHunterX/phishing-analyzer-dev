import logging
from django_huey import task

from .models import Message
from .services.ai_analysis import analyze_message, save_analysis_result

logger = logging.getLogger(__name__)


@task()
def test_background_task():
    logger.error("Huey test task ran successfully.")
    return "ok"


@task()
def run_ai_analysis_task(message_id):
    try:
        message = Message.objects.get(id=message_id)
        analysis_data = analyze_message(message)
        save_analysis_result(message, analysis_data)
        logger.info(f"AI analysis completed for message {message_id}")
    except Message.DoesNotExist:
        logger.error(f"AI task failed: message {message_id} does not exist")
    except Exception as e:
        logger.exception(f"AI task failed for message {message_id}: {e}")