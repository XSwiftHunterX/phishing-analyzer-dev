from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class ModerationStatus(models.TextChoices):
    APPROVED = "approved", "Approved"
    PENDING = "pending", "Pending Review"
    REJECTED = "rejected", "Rejected"

class Message(models.Model):
    MESSAGE_TYPES = [
        ('Email', 'Email'),
        ('SMS', 'SMS'),
    ]

    CLASSIFICATIONS = [
        ('Phishing', 'Phishing'),
        ('Legitimate', 'Legitimate'),
        ('Unsure', 'Unsure'),
    ]


    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    message_content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES)
    sender = models.CharField(max_length=255, blank=True)
    additional_details = models.TextField(blank=True)
    classification = models.CharField(max_length=20, choices=CLASSIFICATIONS)
    submission_date = models.DateTimeField(auto_now_add=True)
    likes = models.ManyToManyField(User, related_name='liked_messages', blank=True)
    screenshot = models.ImageField(upload_to='message_screenshots/', blank=True, null=True)
    redacted_screenshot = models.ImageField(
        upload_to='redacted_message_screenshots/',
        blank=True,
        null=True
    )
    image_moderation_labels = models.JSONField(blank=True, null=True)
    image_relevance_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.APPROVED,
    )
    image_relevance_reason = models.TextField(blank=True)

    is_approved = models.BooleanField(default=True)
    is_flagged = models.BooleanField(default=False)
    is_removed = models.BooleanField(default=False)

    moderation_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.APPROVED,
    )
    moderation_reason = models.TextField(blank=True)
    moderation_score = models.FloatField(default=0.0)
    requires_human_review = models.BooleanField(default=False)

    image_moderation_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.APPROVED,
    )
    image_moderation_reason = models.TextField(blank=True)

    pii_scan_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.APPROVED,
    )
    pii_detected = models.BooleanField(default=False)
    pii_review_required = models.BooleanField(default=False)
    pii_notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.message_type} - {self.classification}"

class AIAnalysis(models.Model):
    VERDICT_CHOICES = [
        ('likely_phishing', 'Likely Phishing'),
        ('suspicious', 'Suspicious'),
        ('unclear', 'Unclear'),
        ('likely_legitimate', 'Likely Legitimate'),
    ]

    message = models.OneToOneField(
        Message,
        on_delete=models.CASCADE,
        related_name='ai_analysis'
    )
    verdict = models.CharField(max_length=30, choices=VERDICT_CHOICES)
    confidence_score = models.PositiveIntegerField()
    summary = models.TextField(blank=True)
    red_flags = models.JSONField(default=list, blank=True)
    recommended_action = models.TextField(blank=True)

    detected_urls = models.JSONField(default=list, blank=True)
    detected_domains = models.JSONField(default=list, blank=True)
    detected_emails = models.JSONField(default=list, blank=True)
    detected_phone_numbers = models.JSONField(default=list, blank=True)

    impersonated_brand = models.CharField(max_length=100, blank=True)
    scam_category = models.CharField(max_length=100, blank=True)
    requested_action = models.CharField(max_length=255, blank=True)

    model_name = models.CharField(max_length=100, blank=True)
    analysis_version = models.CharField(max_length=50, blank=True)
    raw_response = models.JSONField(blank=True, null=True)

    analyzed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AI Analysis for message {self.message.id}"

class Comment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    likes = models.ManyToManyField(User, related_name='liked_comments', blank=True)

    is_flagged = models.BooleanField(default=False)
    is_removed = models.BooleanField(default=False)

    moderation_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.APPROVED,
    )
    moderation_reason = models.TextField(blank=True)
    moderation_score = models.FloatField(default=0.0)
    requires_human_review = models.BooleanField(default=False)

    def __str__(self):
        return f"Comment by {self.user.username} on message {self.message.id}"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True)

    moderation_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.APPROVED,
    )
    moderation_reason = models.TextField(blank=True)
    moderation_score = models.FloatField(default=0.0)
    requires_human_review = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username}'s profile"

class MessageReport(models.Model):
    REPORT_REASONS = [
        ('spam', 'Spam'),
        ('abuse', 'Abusive or harmful content'),
        ('misinformation', 'Misleading classification'),
        ('privacy', 'Contains sensitive personal information'),
        ('other', 'Other'),
    ]

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.CharField(max_length=30, choices=REPORT_REASONS)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_reviewed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('message', 'reporter')

    def __str__(self):
        return f"Report on message {self.message.id} by {self.reporter.username}"


class CommentReport(models.Model):
    REPORT_REASONS = [
        ('spam', 'Spam'),
        ('abuse', 'Abusive or harmful content'),
        ('misinformation', 'Misleading or unhelpful content'),
        ('privacy', 'Contains sensitive personal information'),
        ('other', 'Other'),
    ]

    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.CharField(max_length=30, choices=REPORT_REASONS)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_reviewed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('comment', 'reporter')

    def __str__(self):
        return f"Report on comment {self.comment.id} by {self.reporter.username}"