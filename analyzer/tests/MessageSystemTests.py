from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from analyzer.models import Message, Comment, ModerationStatus, UserProfile
from analyzer.tasks import (
    run_ai_analysis_task,
    run_image_processing_task,
    finalize_message_task,
    check_message_processing_timeout_task,
)
from analyzer.services.message_processing import reset_message_processing_state
from unittest.mock import patch, Mock
from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from analyzer import views
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
import io


class MessageSystemTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ben",
            password="testpass123"
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            password="testpass123"
        )
        self.client.login(username="ben", password="testpass123")
        self.factory = RequestFactory()

    def build_request_with_messages(self, request):
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()

        setattr(request, "_messages", FallbackStorage(request))
        return request

    def make_test_image_file(self, name="test.png", image_format="PNG", size=(100, 100)):
        buffer = io.BytesIO()
        image = Image.new("RGB", size, "white")
        image.save(buffer, format=image_format)
        buffer.seek(0)
        return SimpleUploadedFile(
            name=name,
            content=buffer.read(),
            content_type=f"image/{image_format.lower()}"
        )

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

    def test_non_owner_cannot_edit_message(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Test message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
        )

        response = self.client.get(reverse("edit_message", args=[message.id]))

        self.assertRedirects(response, reverse("message_list"))

    def test_non_owner_cannot_delete_message(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Test message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
        )

        response = self.client.get(reverse("delete_message", args=[message.id]))

        self.assertRedirects(response, reverse("message_list"))

    def test_owner_can_view_own_pending_message(self):
        message = Message.objects.create(
            user=self.user,
            message_content="Pending message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.PENDING,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pending Review")

    def test_non_owner_cannot_view_pending_message(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Pending message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.PENDING,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertRedirects(response, reverse("message_list"))

    def test_owner_can_view_own_pending_comment(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
        )

        comment = Comment.objects.create(
            message=message,
            user=self.user,
            content="Pending comment",
            moderation_status=ModerationStatus.PENDING,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, comment.content)

    def test_non_owner_cannot_view_pending_comment(self):
        message = Message.objects.create(
            user=self.user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        Comment.objects.create(
            message=message,
            user=self.other_user,
            content="Pending comment",
            moderation_status=ModerationStatus.PENDING,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Pending comment")

    def test_rejected_message_is_not_available_to_public(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Rejected message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.REJECTED,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertRedirects(response, reverse("message_list"))

    def test_approved_message_is_visible_to_public(self):
        self.client.logout()

        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved public message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approved public message")

    def test_pending_message_is_visible_to_owner_only(self):
        message = Message.objects.create(
            user=self.user,
            message_content="Owner pending message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.PENDING,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pending Review")
        self.assertContains(response, "only visible to you right now")

    def test_rejected_comment_is_not_shown(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        Comment.objects.create(
            message=message,
            user=self.other_user,
            content="Rejected comment",
            moderation_status=ModerationStatus.REJECTED,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Rejected comment")

    def test_approved_comment_is_shown(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        Comment.objects.create(
            message=message,
            user=self.other_user,
            content="Approved comment",
            moderation_status=ModerationStatus.APPROVED,
        )

        response = self.client.get(reverse("message_detail", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approved comment")

    def test_duplicate_submission_flag_keeps_message_pending_after_finalization(self):
        message = Message.objects.create(
            user=self.user,
            message_content="Duplicate candidate",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.PENDING,
            processing_status="processing",
            ai_status="completed",
            image_processing_status="completed",
            is_finalized=False,
            duplicate_submission_suspected=True,
        )

        finalize_message_task.call_local(message.id)
        message.refresh_from_db()

        self.assertEqual(message.processing_status, "completed")
        self.assertTrue(message.is_finalized)
        self.assertEqual(message.moderation_status, ModerationStatus.PENDING)
        self.assertIn("Possible duplicate submission in a short time.", message.moderation_reason)

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

    def test_message_form_honeypot_blocks_submission(self):
        response = self.client.post(
            reverse("submit_message"),
            {
                "message_content": "Test phishing message",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "spam-bot-filled-this",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Submission could not be processed.")
        self.assertEqual(Message.objects.count(), 0)

    def test_comment_form_honeypot_blocks_submission(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.post(
            reverse("message_detail", args=[message.id]),
            {
                "content": "This is a comment",
                "website": "spam-bot-filled-this",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Comment could not be processed.")
        self.assertEqual(Comment.objects.count(), 0)

    @patch("analyzer.forms.moderate_text")
    def test_signup_form_rejects_prohibited_username(self, mock_moderate_text):
        self.client.logout()

        def fake_moderate(value, context=None):
            result = Mock()
            if context == "username":
                result.status = "rejected"
                result.reason = "Blocked username"
            else:
                result.status = "approved"
                result.reason = ""
            return result

        mock_moderate_text.side_effect = fake_moderate

        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "badusername",
                "email": "bad@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
                "website": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This username is not allowed.")

    @patch("analyzer.forms.moderate_text")
    def test_message_form_rejects_prohibited_message_content(self, mock_moderate_text):
        def fake_moderate(value, context=None):
            result = Mock()
            if context == "message_content":
                result.status = "rejected"
                result.reason = "Blocked content"
            else:
                result.status = "approved"
                result.reason = ""
            return result

        mock_moderate_text.side_effect = fake_moderate

        response = self.client.post(
            reverse("submit_message"),
            {
                "message_content": "Blocked content here",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This message content contains text that is not allowed.")
        self.assertEqual(Message.objects.count(), 0)

    @patch("analyzer.forms.moderate_text")
    def test_comment_form_rejects_prohibited_content(self, mock_moderate_text):
        result = Mock()
        result.status = "rejected"
        result.reason = "Blocked comment"
        mock_moderate_text.return_value = result

        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.post(
            reverse("message_detail", args=[message.id]),
            {
                "content": "Blocked comment text",
                "website": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your comment contains language that is not allowed.")
        self.assertEqual(Comment.objects.count(), 0)

    @patch("analyzer.views.queue_message_processing")
    def test_retry_view_resets_failed_message(self, mock_queue):
        message = Message.objects.create(
            user=self.user,
            message_content="Failed message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.PENDING,
            processing_status="failed",
            processing_error="AI analysis failed",
            processing_failure_type="ai_failure",
            ai_status="failed",
            image_processing_status="pending",
            is_finalized=False,
        )

        response = self.client.get(reverse("retry_message_processing", args=[message.id]))
        message.refresh_from_db()

        self.assertRedirects(response, reverse("processing_message", args=[message.id]))
        self.assertEqual(message.processing_status, "pending")
        self.assertEqual(message.processing_error, "")
        self.assertEqual(message.processing_failure_type, "")
        self.assertEqual(message.ai_status, "pending")
        self.assertEqual(message.image_processing_status, "pending")
        self.assertFalse(message.is_finalized)
        mock_queue.assert_called_once()

    @patch("analyzer.views.queue_message_processing")
    def test_retry_view_does_not_retry_non_failed_message(self, mock_queue):
        message = Message.objects.create(
            user=self.user,
            message_content="Completed message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            ai_status="completed",
            image_processing_status="completed",
            is_finalized=True,
        )

        response = self.client.get(reverse("retry_message_processing", args=[message.id]))

        self.assertRedirects(response, reverse("message_detail", args=[message.id]))
        mock_queue.assert_not_called()

    @patch("analyzer.views.queue_message_processing")
    def test_non_owner_cannot_retry_another_users_message(self, mock_queue):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Failed other user's message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.PENDING,
            processing_status="failed",
            processing_error="AI analysis failed",
            processing_failure_type="ai_failure",
            ai_status="failed",
            image_processing_status="pending",
            is_finalized=False,
        )

        response = self.client.get(reverse("retry_message_processing", args=[message.id]))

        self.assertEqual(response.status_code, 404)
        mock_queue.assert_not_called()

    def test_duplicate_comment_is_marked_pending(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        Comment.objects.create(
            message=message,
            user=self.user,
            content="Repeated comment",
            moderation_status=ModerationStatus.APPROVED,
        )

        response = self.client.post(
            reverse("message_detail", args=[message.id]),
            {
                "content": "Repeated comment",
                "website": "",
            },
        )

        self.assertRedirects(response, reverse("message_detail", args=[message.id]))
        new_comment = Comment.objects.exclude(content="").latest("id")
        self.assertEqual(new_comment.moderation_status, ModerationStatus.PENDING)
        self.assertIn("Possible duplicate comment", new_comment.moderation_reason)

    def test_duplicate_message_sets_duplicate_flag(self):
        Message.objects.create(
            user=self.user,
            message_content="Repeated message body",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.post(
            reverse("submit_message"),
            {
                "message_content": "Repeated message body",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        message = Message.objects.latest("id")
        self.assertTrue(message.duplicate_submission_suspected)

    def test_user_cannot_report_same_message_twice(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        response1 = self.client.post(
            reverse("report_message", args=[message.id]),
            {
                "reason": "spam",
                "details": "first report",
            },
        )
        self.assertRedirects(response1, reverse("message_detail", args=[message.id]))

        response2 = self.client.post(
            reverse("report_message", args=[message.id]),
            {
                "reason": "spam",
                "details": "second report",
            },
        )
        self.assertRedirects(response2, reverse("message_detail", args=[message.id]))

        self.assertEqual(message.reports.count(), 1)

    def test_user_cannot_report_same_comment_twice(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        comment = Comment.objects.create(
            message=message,
            user=self.other_user,
            content="Approved comment",
            moderation_status=ModerationStatus.APPROVED,
        )

        response1 = self.client.post(
            reverse("report_comment", args=[comment.id]),
            {
                "reason": "spam",
                "details": "first report",
            },
        )
        self.assertRedirects(response1, reverse("message_detail", args=[message.id]))

        response2 = self.client.post(
            reverse("report_comment", args=[comment.id]),
            {
                "reason": "spam",
                "details": "second report",
            },
        )
        self.assertRedirects(response2, reverse("message_detail", args=[message.id]))

        self.assertEqual(comment.reports.count(), 1)

    def test_user_cannot_report_same_profile_twice(self):
        profile_user = self.other_user
        UserProfile.objects.get_or_create(user=profile_user)

        response1 = self.client.post(
            reverse("report_profile", args=[profile_user.username]),
            {
                "reason": "spam",
                "details": "first report",
            },
        )
        self.assertRedirects(response1, reverse("user_messages", args=[profile_user.username]))

        response2 = self.client.post(
            reverse("report_profile", args=[profile_user.username]),
            {
                "reason": "spam",
                "details": "second report",
            },
        )
        self.assertRedirects(response2, reverse("user_messages", args=[profile_user.username]))

        profile = UserProfile.objects.get(user=profile_user)
        self.assertEqual(profile.reports.count(), 1)

    def test_approved_messages_appear_in_message_list(self):
        Message.objects.create(
            user=self.other_user,
            message_content="Visible approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
            is_removed=False,
        )

        response = self.client.get(reverse("message_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible approved message")

    def test_pending_messages_do_not_appear_in_public_message_list(self):
        Message.objects.create(
            user=self.other_user,
            message_content="Hidden pending message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.PENDING,
            processing_status="completed",
            is_finalized=True,
            is_removed=False,
        )

        response = self.client.get(reverse("message_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Hidden pending message")

    def test_rejected_messages_do_not_appear_in_public_message_list(self):
        Message.objects.create(
            user=self.other_user,
            message_content="Hidden rejected message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.REJECTED,
            processing_status="completed",
            is_finalized=True,
            is_removed=False,
        )

        response = self.client.get(reverse("message_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Hidden rejected message")

    def test_removed_messages_do_not_appear_in_public_message_list(self):
        Message.objects.create(
            user=self.other_user,
            message_content="Removed message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
            is_removed=True,
        )

        response = self.client.get(reverse("message_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Removed message")

    def test_similar_messages_only_shown_for_approved_message(self):
        pending_message = Message.objects.create(
            user=self.user,
            message_content="Pending message content",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.PENDING,
            processing_status="completed",
            is_finalized=True,
        )

        response = self.client.get(reverse("message_detail", args=[pending_message.id]))

        self.assertEqual(response.status_code, 200)
        similar_messages = response.context["similar_messages"]
        self.assertEqual(similar_messages, [])

    @patch("analyzer.views.check_message_processing_timeout_task.schedule")
    @patch("analyzer.views.run_image_processing_task")
    @patch("analyzer.views.run_ai_analysis_task")
    def test_submit_message_calls_tasks_and_redirects_to_processing(
        self, mock_ai_task, mock_image_task, mock_timeout_schedule
    ):
        response = self.client.post(
            reverse("submit_message"),
            {
                "message_content": "New phishing message",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
            },
        )

        message = Message.objects.latest("id")

        self.assertRedirects(response, reverse("processing_message", args=[message.id]))
        self.assertEqual(message.processing_status, "pending")
        self.assertFalse(message.is_finalized)
        self.assertEqual(message.moderation_status, ModerationStatus.PENDING)

        mock_ai_task.assert_called_once_with(message.id)
        mock_image_task.assert_called_once_with(message.id)
        mock_timeout_schedule.assert_called_once()

    def test_processing_message_page_loads_for_owner_while_pending(self):
        message = self.create_message()

        response = self.client.get(reverse("processing_message", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "processing")

    def test_processing_message_redirects_to_detail_when_completed(self):
        message = self.create_message()
        message.processing_status = "completed"
        message.is_finalized = True
        message.save(update_fields=["processing_status", "is_finalized"])

        response = self.client.get(reverse("processing_message", args=[message.id]))

        self.assertRedirects(response, reverse("message_detail", args=[message.id]))

    def test_non_owner_cannot_access_processing_message(self):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Other user's message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            processing_status="pending",
            ai_status="pending",
            image_processing_status="pending",
            moderation_status=ModerationStatus.PENDING,
            is_finalized=False,
        )

        response = self.client.get(reverse("processing_message", args=[message.id]))
        self.assertEqual(response.status_code, 404)

    def test_message_processing_status_returns_ready_false_while_processing(self):
        message = self.create_message()
        message.processing_status = "processing"
        message.is_finalized = False
        message.save(update_fields=["processing_status", "is_finalized"])

        response = self.client.get(reverse("message_processing_status", args=[message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "ready": False,
                "failed": False,
                "ai_status": message.ai_status,
                "image_processing_status": message.image_processing_status,
                "processing_status": "processing",
                "processing_error": "",
                "redirect_url": "",
                "message_id": message.id,
            },
        )

    def test_message_processing_status_returns_ready_true_when_completed(self):
        message = self.create_message()
        message.processing_status = "completed"
        message.ai_status = "completed"
        message.image_processing_status = "completed"
        message.is_finalized = True
        message.save()

        response = self.client.get(reverse("message_processing_status", args=[message.id]))
        data = response.json()

        self.assertTrue(data["ready"])
        self.assertFalse(data["failed"])
        self.assertEqual(
            data["redirect_url"],
            reverse("message_detail", args=[message.id])
        )

    @patch("analyzer.tasks.finalize_message_task")
    def test_maybe_queue_finalize_calls_finalize_only_when_both_complete(self, mock_finalize):
        message = self.create_message()
        message.ai_status = "completed"
        message.image_processing_status = "completed"
        message.processing_status = "processing"
        message.is_finalized = False
        message.save()

        from analyzer.tasks import maybe_queue_finalize
        maybe_queue_finalize(message.id)

        mock_finalize.assert_called_once_with(message.id)

    def test_timeout_check_skips_completed_message(self):
        message = self.create_message()
        message.processing_status = "completed"
        message.is_finalized = True
        message.save(update_fields=["processing_status", "is_finalized"])

        check_message_processing_timeout_task.call_local(message.id)
        message.refresh_from_db()

        self.assertEqual(message.processing_status, "completed")
        self.assertTrue(message.is_finalized)

    @patch("analyzer.views.add_ratelimit_message")
    def test_submit_message_rate_limited_redirects_without_creating_message(self, mock_add_message):
        request = self.factory.post(
            reverse("submit_message"),
            {
                "message_content": "Rate limited message",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
            },
        )
        request.user = self.user
        request.limited = True
        request = self.build_request_with_messages(request)

        response = views.submit_message(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("submit_message"))
        self.assertEqual(Message.objects.count(), 0)
        mock_add_message.assert_called_once_with(request, "submit_message")

    @patch("analyzer.views.add_ratelimit_message")
    def test_comment_rate_limited_redirects_without_creating_comment(self, mock_add_message):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Approved message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        request = self.factory.post(
            reverse("message_detail", args=[message.id]),
            {"content": "Blocked by rate limit", "website": ""},
        )
        request.user = self.user
        request.limited = True
        request = self.build_request_with_messages(request)

        response = views.message_detail(request, message.id)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("message_detail", args=[message.id]))
        self.assertEqual(Comment.objects.count(), 0)
        mock_add_message.assert_called_once_with(request, "comment")

    @patch("analyzer.views.add_ratelimit_message")
    def test_edit_message_rate_limited_redirects_without_updating_message(self, mock_add_message):
        message = Message.objects.create(
            user=self.user,
            message_content="Original content",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        request = self.factory.post(
            reverse("edit_message", args=[message.id]),
            {
                "message_content": "Changed content",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
            },
        )
        request.user = self.user
        request.limited = True
        request = self.build_request_with_messages(request)

        response = views.edit_message(request, message.id)
        message.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("edit_message", args=[message.id]))
        self.assertEqual(message.message_content, "Original content")
        mock_add_message.assert_called_once_with(request, "edit_message")

    @patch("analyzer.views.add_ratelimit_message")
    def test_report_message_rate_limited_redirects_without_creating_report(self, mock_add_message):
        message = Message.objects.create(
            user=self.other_user,
            message_content="Reportable message",
            message_type="Email",
            sender="alerts@example.com",
            platform="Gmail",
            additional_details="",
            classification="Phishing",
            moderation_status=ModerationStatus.APPROVED,
            processing_status="completed",
            is_finalized=True,
        )

        request = self.factory.post(
            reverse("report_message", args=[message.id]),
            {"reason": "spam", "details": "Too many reports"},
        )
        request.user = self.user
        request.limited = True
        request = self.build_request_with_messages(request)

        response = views.report_message(request, message.id)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("message_detail", args=[message.id]))
        self.assertEqual(message.reports.count(), 0)
        mock_add_message.assert_called_once_with(request, "report_message")

    def test_message_list_paginates_after_ten_messages(self):
        for i in range(11):
            Message.objects.create(
                user=self.other_user,
                message_content=f"Approved message {i}",
                message_type="Email",
                sender="alerts@example.com",
                platform="Gmail",
                additional_details="",
                classification="Phishing",
                moderation_status=ModerationStatus.APPROVED,
                processing_status="completed",
                is_finalized=True,
                is_removed=False,
            )

        response = self.client.get(reverse("message_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["message_page"]), 10)
        self.assertTrue(response.context["message_page"].has_next())
        self.assertEqual(response.context["message_page"].number, 1)

    def test_message_list_second_page_contains_remaining_messages(self):
        for i in range(11):
            Message.objects.create(
                user=self.other_user,
                message_content=f"Approved message {i}",
                message_type="Email",
                sender="alerts@example.com",
                platform="Gmail",
                additional_details="",
                classification="Phishing",
                moderation_status=ModerationStatus.APPROVED,
                processing_status="completed",
                is_finalized=True,
                is_removed=False,
            )

        response = self.client.get(reverse("message_list") + "?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["message_page"]), 1)
        self.assertTrue(response.context["message_page"].has_previous())
        self.assertEqual(response.context["message_page"].number, 2)

    @patch("analyzer.views.moderate_profile_image")
    def test_edit_profile_rejects_disallowed_profile_image(self, mock_moderate_profile_image):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.bio = "Old bio"
        profile.save()

        mock_result = Mock()
        mock_result.allowed = False
        mock_result.reason = "This image is not allowed."
        mock_moderate_profile_image.return_value = mock_result

        response = self.client.post(
            reverse("edit_profile"),
            {
                "username": self.user.username,
                "first_name": "",
                "last_name": "",
                "email": "ben@test.com",
                "bio": "Updated bio",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This image is not allowed.")

        profile.refresh_from_db()
        self.assertEqual(profile.bio, "Old bio")

    @patch("analyzer.forms.moderate_text")
    @patch("analyzer.views.moderate_profile_image")
    def test_edit_profile_rejects_moderated_bio(self, mock_moderate_profile_image, mock_moderate_text):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.bio = "Old bio"
        profile.save()

        image_result = Mock()
        image_result.allowed = True
        image_result.reason = ""
        mock_moderate_profile_image.return_value = image_result

        def fake_moderate(value, context=None):
            result = Mock()
            if context == "profile_bio":
                result.status = "rejected"
                result.reason = "Blocked bio"
            elif context == "username":
                result.status = "approved"
                result.reason = ""
            else:
                result.status = "approved"
                result.reason = ""
            return result

        mock_moderate_text.side_effect = fake_moderate

        response = self.client.post(
            reverse("edit_profile"),
            {
                "username": self.user.username,
                "first_name": "",
                "last_name": "",
                "email": "ben@test.com",
                "bio": "Blocked bio content",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Your bio contains language that is not allowed. Please revise it and try again."
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "Old bio")

    @patch("analyzer.views.moderate_profile_image")
    @patch("analyzer.forms.moderate_text")
    def test_edit_profile_allows_clean_bio_and_updates_profile(self, mock_moderate_text, mock_moderate_profile_image):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.bio = "Old bio"
        profile.save()

        image_result = Mock()
        image_result.allowed = True
        image_result.reason = ""
        mock_moderate_profile_image.return_value = image_result

        def fake_moderate(value, context=None):
            result = Mock()
            result.status = "approved"
            result.reason = ""
            return result

        mock_moderate_text.side_effect = fake_moderate

        response = self.client.post(
            reverse("edit_profile"),
            {
                "username": self.user.username,
                "first_name": "Ben",
                "last_name": "Churchill",
                "email": "ben@test.com",
                "bio": "New clean bio",
            },
        )

        self.assertRedirects(response, reverse("profile"))

        profile = UserProfile.objects.get(user=self.user)
        self.user.refresh_from_db()

        self.assertEqual(profile.bio, "New clean bio")
        self.assertEqual(self.user.first_name, "Ben")
        self.assertEqual(self.user.last_name, "Churchill")

    @patch("analyzer.views.check_message_processing_timeout_task.schedule")
    @patch("analyzer.views.run_image_processing_task")
    @patch("analyzer.views.run_ai_analysis_task")
    def test_submit_message_accepts_valid_png_upload(
        self, mock_ai_task, mock_image_task, mock_timeout_schedule
    ):
        image_file = self.make_test_image_file(name="proof.png", image_format="PNG")

        response = self.client.post(
            reverse("submit_message"),
            {
                "message_content": "Suspicious message with screenshot",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
                "screenshot": image_file,
            },
        )

        self.assertEqual(response.status_code, 302)
        message = Message.objects.latest("id")
        self.assertTrue(bool(message.screenshot))

    def test_submit_message_rejects_unsupported_file_extension(self):
        fake_file = SimpleUploadedFile(
            "not_allowed.gif",
            b"fake image content",
            content_type="image/gif"
        )

        response = self.client.post(
            reverse("submit_message"),
            {
                "message_content": "Message with bad file type",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
                "screenshot": fake_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a valid image")
        self.assertEqual(Message.objects.count(), 0)

    def test_submit_message_rejects_fake_image_file(self):
        fake_file = SimpleUploadedFile(
            "fake.png",
            b"This is not really an image",
            content_type="image/png"
        )

        response = self.client.post(
            reverse("submit_message"),
            {
                "message_content": "Message with fake image",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
                "screenshot": fake_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Upload a valid image. The file you uploaded was either not an image or a corrupted image."
        )
        self.assertEqual(Message.objects.count(), 0)

    @patch("analyzer.validators.MAX_IMAGE_FILE_SIZE", 1)  # force tiny limit
    def test_submit_message_rejects_oversized_image(self):
        image_file = self.make_test_image_file(name="large.png", image_format="PNG")
        big_content = b"a" * (6 * 1024 * 1024)
        image_file = SimpleUploadedFile(
            "big.png",
            big_content,
            content_type="image/png"
        )

        response = self.client.post(
            reverse("submit_message"),
            {
                "message_content": "Message with large image",
                "message_type": "Email",
                "sender": "alerts@example.com",
                "platform": "Gmail",
                "additional_details": "",
                "classification": "Phishing",
                "website": "",
                "screenshot": image_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a valid image")
        self.assertEqual(Message.objects.count(), 0)

    @patch("analyzer.views.moderate_profile_image")
    @patch("analyzer.forms.moderate_text")
    def test_edit_profile_accepts_valid_png_upload(self, mock_moderate_text, mock_moderate_profile_image):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)

        text_result = Mock()
        text_result.status = "approved"
        text_result.reason = ""
        mock_moderate_text.return_value = text_result

        image_result = Mock()
        image_result.allowed = True
        image_result.reason = ""
        mock_moderate_profile_image.return_value = image_result

        image_file = self.make_test_image_file(name="avatar.png", image_format="PNG")

        response = self.client.post(
            reverse("edit_profile"),
            {
                "username": self.user.username,
                "first_name": "",
                "last_name": "",
                "email": "ben@test.com",
                "bio": "Clean bio",
                "profile_image": image_file,
            },
        )

        self.assertRedirects(response, reverse("profile"))
        profile.refresh_from_db()
        self.assertTrue(bool(profile.profile_image))

    @patch("analyzer.forms.moderate_text")
    def test_edit_profile_rejects_unsupported_profile_image_extension(self, mock_moderate_text):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)

        text_result = Mock()
        text_result.status = "approved"
        text_result.reason = ""
        mock_moderate_text.return_value = text_result

        fake_file = SimpleUploadedFile(
            "avatar.gif",
            b"fake image content",
            content_type="image/gif"
        )

        response = self.client.post(
            reverse("edit_profile"),
            {
                "username": self.user.username,
                "first_name": "",
                "last_name": "",
                "email": "ben@test.com",
                "bio": "Clean bio",
                "profile_image": fake_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a valid image")
        profile.refresh_from_db()
        self.assertFalse(bool(profile.profile_image))

    @patch("analyzer.forms.moderate_text")
    def test_edit_profile_rejects_fake_profile_image_file(self, mock_moderate_text):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)

        text_result = Mock()
        text_result.status = "approved"
        text_result.reason = ""
        mock_moderate_text.return_value = text_result

        fake_file = SimpleUploadedFile(
            "avatar.png",
            b"This is not really an image",
            content_type="image/png"
        )

        response = self.client.post(
            reverse("edit_profile"),
            {
                "username": self.user.username,
                "first_name": "",
                "last_name": "",
                "email": "ben@test.com",
                "bio": "Clean bio",
                "profile_image": fake_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Upload a valid image. The file you uploaded was either not an image or a corrupted image."
        )
        profile.refresh_from_db()
        self.assertFalse(bool(profile.profile_image))

    @patch("analyzer.validators.MAX_IMAGE_FILE_SIZE", 1)  # force tiny limit
    @patch("analyzer.forms.moderate_text")
    def test_edit_profile_rejects_oversized_profile_image(self, mock_moderate_text):
        profile, _ = UserProfile.objects.get_or_create(user=self.user)

        text_result = Mock()
        text_result.status = "approved"
        text_result.reason = ""
        mock_moderate_text.return_value = text_result

        image_file = self.make_test_image_file(name="big.png", image_format="PNG")
        big_content = b"a" * (6 * 1024 * 1024)
        image_file = SimpleUploadedFile(
            "big.png",
            big_content,
            content_type="image/png"
        )

        response = self.client.post(
            reverse("edit_profile"),
            {
                "username": self.user.username,
                "first_name": "",
                "last_name": "",
                "email": "ben@test.com",
                "bio": "Clean bio",
                "profile_image": image_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a valid image")
        profile.refresh_from_db()
        self.assertFalse(bool(profile.profile_image))