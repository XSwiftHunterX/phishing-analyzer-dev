from django.contrib import admin
from .models import Message, Comment, UserProfile, MessageReport, CommentReport, AIAnalysis

# Register your models here.
@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'message_type', 'classification', 'suspected_risk',
        'user', 'submission_date', 'is_approved', 'is_flagged', 'is_removed'
    )
    list_filter = ('message_type', 'classification', 'suspected_risk', 'is_approved', 'is_flagged', 'is_removed')
    search_fields = ('message_content', 'sender', 'user__username')
    ordering = ('-submission_date',)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'message', 'created_at', 'is_flagged', 'is_removed')
    list_filter = ('is_flagged', 'is_removed', 'created_at')
    search_fields = ('content', 'user__username', 'message__message_content')
    ordering = ('-created_at',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user')
    search_fields = ('user__username', 'user__email')


@admin.register(MessageReport)
class MessageReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'message', 'reporter', 'reason', 'created_at', 'is_reviewed')
    list_filter = ('reason', 'is_reviewed', 'created_at')
    search_fields = ('message__message_content', 'reporter__username', 'details')
    ordering = ('-created_at',)


@admin.register(CommentReport)
class CommentReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'comment', 'reporter', 'reason', 'created_at', 'is_reviewed')
    list_filter = ('reason', 'is_reviewed', 'created_at')
    search_fields = ('comment__content', 'reporter__username', 'details')
    ordering = ('-created_at',)

@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'message', 'verdict', 'confidence_score', 'model_name', 'analyzed_at')
    list_filter = ('verdict', 'model_name', 'analyzed_at')
    search_fields = ('message__message_content', 'message__sender', 'summary')
    ordering = ('-analyzed_at',)