from django import forms
from .models import Message


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['message_content', 'message_type', 'classification', 'risk_level']