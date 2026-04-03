from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from analyzer.models import Message
from analyzer.tasks import (
    run_ai_analysis_task,
    run_image_processing_task,
    finalize_message_task,
    check_message_processing_timeout_task,
)
from analyzer.services.message_processing import reset_message_processing_state


class AsyncProcessingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ben",
            password="testpass123"
        )
        self.client.login(username="ben", password="testpass123")

    def create_message(self):
        return Message.objects.create(
            user=self.user,
            message_content="Your account is suspended. Click here now.",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            processing_status="pending",
            ai_status="pending",
            image_processing_status="pending",
            moderation_status="pending",
            is_finalized=False,
        )

    @patch("analyzer.tasks.analyze_message")
    @patch("analyzer.tasks.save_analysis_result")
    def test_successful_processing_completes_message(self, mock_save_analysis, mock_analyze):
        mock_analyze.return_value = {
            "verdict": "likely_phishing",
            "confidence_score": 90,
            "summary": "Suspicious phishing indicators",
            "red_flags": ["urgent tone"],
            "recommended_action": "Do not click links",
        }

        message = self.create_message()

        run_ai_analysis_task.call_local(message.id)
        run_image_processing_task.call_local(message.id)

        message.refresh_from_db()

        self.assertEqual(message.ai_status, "completed")
        self.assertEqual(message.image_processing_status, "completed")

        finalize_message_task.call_local(message.id)
        message.refresh_from_db()

        self.assertEqual(message.processing_status, "completed")
        self.assertTrue(message.is_finalized)
        self.assertEqual(message.processing_error, "")
        self.assertEqual(message.processing_failure_type, "")

    @patch("analyzer.tasks.analyze_message", side_effect=Exception("Gemini failed"))
    def test_ai_failure_marks_message_failed(self, mock_analyze):
        message = self.create_message()

        run_ai_analysis_task.call_local(message.id)
        message.refresh_from_db()

        self.assertEqual(message.ai_status, "failed")
        self.assertEqual(message.processing_status, "failed")
        self.assertEqual(message.processing_failure_type, "ai_failure")
        self.assertIn("AI analysis failed", message.processing_error)
        self.assertFalse(message.is_finalized)

    @patch("analyzer.tasks.moderate_uploaded_image", side_effect=Exception("Rekognition failed"))
    def test_image_failure_marks_message_failed(self, mock_image):
        message = self.create_message()

        message.screenshot = "fake.jpg"
        message.save(update_fields=["screenshot"])

        run_image_processing_task.call_local(message.id)
        message.refresh_from_db()

        self.assertEqual(message.image_processing_status, "failed")
        self.assertEqual(message.processing_status, "failed")
        self.assertEqual(message.processing_failure_type, "image_failure")
        self.assertIn("Image processing failed", message.processing_error)
        self.assertFalse(message.is_finalized)

    @patch("analyzer.tasks.settings.MESSAGE_PROCESSING_TIMEOUT_SECONDS", 1)
    def test_timeout_marks_message_failed(self):
        message = self.create_message()

        from django.utils import timezone
        from datetime import timedelta

        message.processing_started_at = timezone.now() - timedelta(seconds=5)
        message.processing_status = "processing"
        message.save(update_fields=["processing_started_at", "processing_status"])

        check_message_processing_timeout_task.call_local(message.id)
        message.refresh_from_db()

        self.assertEqual(message.processing_status, "failed")
        self.assertEqual(message.processing_failure_type, "timeout_failure")
        self.assertIn("timed out", message.processing_error)
        self.assertFalse(message.is_finalized)

    def test_reset_message_processing_state_clears_failure_fields(self):
        message = self.create_message()
        message.processing_status = "failed"
        message.processing_error = "AI analysis failed"
        message.processing_failure_type = "ai_failure"
        message.is_finalized = True
        message.ai_status = "failed"
        message.image_processing_status = "completed"
        message.save()

        message = reset_message_processing_state(message)

        self.assertEqual(message.processing_status, "pending")
        self.assertEqual(message.processing_error, "")
        self.assertEqual(message.processing_failure_type, "")
        self.assertFalse(message.is_finalized)
        self.assertEqual(message.ai_status, "pending")
        self.assertEqual(message.image_processing_status, "pending")
        self.assertIsNone(message.processing_completed_at)

    @patch("analyzer.tasks.analyze_message")
    @patch("analyzer.tasks.save_analysis_result")
    def test_finalize_message_task_is_idempotent(self, mock_save_analysis, mock_analyze):
        mock_analyze.return_value = {
            "verdict": "likely_phishing",
            "confidence_score": 90,
            "summary": "Suspicious phishing indicators",
            "red_flags": ["urgent tone"],
            "recommended_action": "Do not click links",
        }

        message = self.create_message()
        message.ai_status = "completed"
        message.image_processing_status = "completed"
        message.processing_status = "processing"
        message.save(update_fields=["ai_status", "image_processing_status", "processing_status"])

        finalize_message_task.call_local(message.id)
        first_completed_at = Message.objects.get(id=message.id).processing_completed_at

        finalize_message_task.call_local(message.id)
        message.refresh_from_db()

        self.assertTrue(message.is_finalized)
        self.assertEqual(message.processing_status, "completed")
        self.assertEqual(message.processing_completed_at, first_completed_at)

    def test_owner_is_redirected_to_processing_page_while_message_processing(self):
        message = self.create_message()
        message.processing_status = "processing"
        message.is_finalized = False
        message.save(update_fields=["processing_status", "is_finalized"])

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertRedirects(response, reverse("processing_message", args=[message.id]))