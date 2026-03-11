from django import forms
from .models import Message, Comment
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['message_content', 'message_type', 'classification', 'suspected_risk']

class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "password1", "password2"]

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']