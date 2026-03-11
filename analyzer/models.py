from django.db import models
from django.contrib.auth.models import User

# Create your models here.
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

    SUSPECTED_RISK_LEVELS = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    message_content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES)
    classification = models.CharField(max_length=20, choices=CLASSIFICATIONS)
    suspected_risk = models.CharField(max_length=10, choices=SUSPECTED_RISK_LEVELS)
    submission_date = models.DateTimeField(auto_now_add=True)
    seconds = models.ManyToManyField(User, related_name='seconded_messages', blank=True)

    def __str__(self):
        return f"{self.message_type} - {self.classification} - {self.suspected_risk}"

class Comment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    likes = models.ManyToManyField(User, related_name='liked_comments', blank=True)

    def __str__(self):
        return f"Comment by {self.user.username} on message {self.message.id}"