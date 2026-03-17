from django import forms
from .models import Message, Comment, UserProfile, MessageReport, CommentReport
from django.contrib.auth.models import User
from allauth.account.forms import LoginForm, SignupForm
from .services.text_moderation import moderate_text

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

    def clean_message_content(self):
        content = self.cleaned_data.get('message_content', '')
        result = moderate_text(content, context="message_content")

        if result.status == "rejected":
            raise forms.ValidationError(
                "This message content contains text that is not allowed."
            )

        self._message_content_moderation = result
        return content

    def clean_sender(self):
        sender = self.cleaned_data.get('sender', '')
        result = moderate_text(sender, context="sender")

        if result.status == "rejected":
            raise forms.ValidationError(
                "The sender field contains text that is not allowed."
            )

        self._sender_moderation = result
        return sender

    def clean_additional_details(self):
        details = self.cleaned_data.get('additional_details', '')
        result = moderate_text(details, context="additional_details")

        if result.status == "rejected":
            raise forms.ValidationError(
                "The additional details field contains text that is not allowed."
            )

        self._additional_details_moderation = result
        return details

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

    def clean_content(self):
        content = self.cleaned_data.get('content', '')
        result = moderate_text(content)

        if result.status == "rejected":
            raise forms.ValidationError(
                "Your comment contains language that is not allowed."
            )

        self._moderation_result = result
        return content

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

    def clean_username(self):
        username = self.cleaned_data.get('username', '')
        result = moderate_text(username, context="username")

        if result.status != "approved":
            raise forms.ValidationError(
                "This username is not allowed."
            )

        return username

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

    def clean_bio(self):
        bio = self.cleaned_data.get('bio', '')
        result = moderate_text(bio, context="profile_bio")

        if result.status == "rejected":
            raise forms.ValidationError(
                "Your bio contains language that is not allowed."
            )

        self._bio_moderation_result = result
        return bio

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

class StyledLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["login"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Enter your email address"
        })
        self.fields["password"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Enter your password"
        })

class StyledSignupForm(SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "email" in self.fields:
            self.fields["email"].widget.attrs.update({
                "class": "form-control",
                "placeholder": "Enter your email address"
            })

        if "password1" in self.fields:
            self.fields["password1"].widget.attrs.update({
                "class": "form-control",
                "placeholder": "Create a password"
            })

        if "password2" in self.fields:
            self.fields["password2"].widget.attrs.update({
                "class": "form-control",
                "placeholder": "Confirm your password"
            })

    def save(self, request):
        user = super().save(request)
        return user