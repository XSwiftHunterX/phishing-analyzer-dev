from django import forms
from .models import Message, Comment, UserProfile, MessageReport, CommentReport
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = [
            'message_content',
            'message_type',
            'sender',
            'additional_details',
            'screenshot',
            'classification',
            'suspected_risk',
        ]
        widgets = {
            'message_type': forms.Select(attrs={'class': 'form-select'}),
            'sender': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter email address, phone number, company name, or sender ID'
            }),
            'classification': forms.Select(attrs={'class': 'form-select'}),
            'suspected_risk': forms.Select(attrs={'class': 'form-select'}),
            'screenshot': forms.ClearableFileInput(attrs={
                'class': 'form-control'
            }),
            'message_content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Paste the full message content here'
            }),
            'additional_details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Add any extra context that may help others evaluate this message'
            }),
        }

class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "password1", "password2"]
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Choose a username"
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Choose a username"
        })
        self.fields["password1"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Create a password"
        })
        self.fields["password2"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Confirm your password"
        })

        self.fields["username"].help_text = "Use letters, numbers, and @/./+/-/_ only."

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Write your comment here'
            }),
        }

class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your username'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your first name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your last name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your email address'
            }),
        }

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['bio', 'profile_image']
        widgets = {
            'bio': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Tell the community a little about yourself'
            }),
            'profile_image': forms.ClearableFileInput(attrs={
                'class': 'form-control'
            }),
        }

class CustomAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Enter your username"
        })
        self.fields["password"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Enter your password"
        })

class MessageReportForm(forms.ModelForm):
    class Meta:
        model = MessageReport
        fields = ['reason', 'details']
        widgets = {
            'reason': forms.Select(attrs={'class': 'form-select'}),
            'details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Add any additional details for the moderators (optional)'
            }),
        }


class CommentReportForm(forms.ModelForm):
    class Meta:
        model = CommentReport
        fields = ['reason', 'details']
        widgets = {
            'reason': forms.Select(attrs={'class': 'form-select'}),
            'details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Add any additional details for the moderators (optional)'
            }),
        }