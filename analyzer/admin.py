from django.contrib import admin
from django.utils.html import format_html, conditional_escape
from django.utils.safestring import mark_safe
from .models import Message, Comment, UserProfile, MessageReport, CommentReport, UserProfileReport, AIAnalysis
from django.urls import reverse

# Register your models here.
@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'message_type',
        'platform',
        'classification',
        'user',
        'submission_date',
        'moderation_status',
        'has_image_issue',
        'has_pii_issue',
        'is_reported',
    )
    list_filter = (
        'moderation_status',
        'is_flagged',
        'message_type',
        'classification',
        'pii_scan_status',
        'image_moderation_status',
        'image_relevance_status',
    )
    search_fields = ('message_content', 'sender', 'platform', 'user__username')
    ordering = ('-submission_date',)

    fieldsets = (
        ('Message Info', {
            'fields': (
                'user',
                'message_type',
                'platform',
                'classification',
                'sender',
                'message_content',
                'additional_details',
                'submission_date',
            )
        }),
        ('Main Moderation', {
            'fields': (
                'moderation_summary',
                'moderation_status',
            )
        }),
        ('Screenshot Files', {
            'fields': (
                'screenshot',
                'redacted_screenshot',
            )
        }),
        ('Image Moderation Details', {
            'classes': ('collapse',),
            'fields': (
                'image_moderation_status',
                'image_moderation_reason',
                'image_moderation_labels',
            )
        }),
        ('Image Relevance Details', {
            'classes': ('collapse',),
            'fields': (
                'image_relevance_status',
                'image_relevance_reason',
            )
        }),
        ('PII Review Details', {
            'classes': ('collapse',),
            'fields': (
                'pii_scan_status',
                'pii_detected',
                'pii_review_required',
                'pii_notes',
            )
        }),
    )

    readonly_fields = (
        'submission_date',
        'moderation_summary',
        'image_moderation_status',
        'image_moderation_reason',
        'image_moderation_labels',
        'image_relevance_status',
        'image_relevance_reason',
        'pii_scan_status',
        'pii_detected',
        'pii_review_required',
        'pii_notes',
    )

    @admin.display(description='Moderation Summary')
    def moderation_summary(self, obj):
        status_colors = {
            'approved': '#198754',
            'pending': '#ffc107',
            'rejected': '#dc3545',
        }
        color = status_colors.get(obj.moderation_status, '#6c757d')

        if obj.moderation_reason:
            escaped_reasons = [
                conditional_escape(part.strip())
                for part in obj.moderation_reason.split('|')
                if part.strip()
            ]
            reason_html = mark_safe('<br>• '.join(escaped_reasons))
            reason_block = mark_safe('• ' + reason_html)
        else:
            reason_block = 'No moderation issues recorded.'

        return format_html(
            """
            <div style="padding: 12px; border: 1px solid #444; border-radius: 8px; background: #111;">
                <div style="margin-bottom: 8px;">
                    <strong>Status:</strong>
                    <span style="
                        display: inline-block;
                        margin-left: 8px;
                        padding: 4px 10px;
                        border-radius: 999px;
                        background: {};
                        color: white;
                        font-weight: 600;
                    ">
                        {}
                    </span>
                </div>
                <div>
                    <strong>Reason:</strong><br>
                    {}
                </div>
            </div>
            """,
            color,
            obj.moderation_status.title(),
            reason_block,
        )

    @admin.display(boolean=True, description='Image Issue')
    def has_image_issue(self, obj):
        return (
            obj.image_moderation_status == 'pending'
            or obj.image_relevance_status == 'pending'
        )

    @admin.display(boolean=True, description='PII Issue')
    def has_pii_issue(self, obj):
        return obj.pii_detected or obj.pii_scan_status == 'pending'

    @admin.display(boolean=True, description='Reported')
    def is_reported(self, obj):
        return obj.is_flagged

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'message',
        'created_at',
        'moderation_status',
    )
    list_filter = ('moderation_status', 'created_at')
    search_fields = ('content', 'user__username', 'message__message_content')
    ordering = ('-created_at',)

    fieldsets = (
        ('Comment Info', {
            'fields': ('message', 'user', 'content', 'created_at')
        }),
        ('Moderation', {
            'fields': (
                'moderation_status',
                'moderation_reason',
            )
        }),
    )

    readonly_fields = ('created_at',)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user')
    search_fields = ('user__username', 'user__email')


@admin.register(MessageReport)
class MessageReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'message_link', 'reporter', 'reason', 'created_at', 'is_reviewed')
    list_filter = ('reason', 'is_reviewed', 'created_at')
    search_fields = ('message__message_content', 'reporter__username', 'details')
    ordering = ('-created_at',)

    @admin.display(description='Reported Message')
    def message_link(self, obj):
        url = reverse('admin:analyzer_message_change', args=[obj.message.id])
        return format_html(
            '<a href="{}">Message #{}</a>',
            url,
            obj.message.id
        )

@admin.register(CommentReport)
class CommentReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'comment_link', 'message_link', 'reporter', 'reason', 'created_at', 'is_reviewed')
    list_filter = ('reason', 'is_reviewed', 'created_at')
    search_fields = ('comment__content', 'reporter__username', 'details')
    ordering = ('-created_at',)

    @admin.display(description='Reported Comment')
    def comment_link(self, obj):
        url = reverse('admin:analyzer_comment_change', args=[obj.comment.id])
        return format_html(
            '<a href="{}">Comment #{}</a>',
            url,
            obj.comment.id
        )

    @admin.display(description='On Message')
    def message_link(self, obj):
        url = reverse('admin:analyzer_message_change', args=[obj.comment.message.id])
        return format_html(
            '<a href="{}">Message #{}</a>',
            url,
            obj.comment.message.id
        )

@admin.register(UserProfileReport)
class UserProfileReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'profile', 'reporter', 'reason', 'created_at', 'is_reviewed')
    list_filter = ('reason', 'is_reviewed', 'created_at')
    search_fields = ('profile__user__username', 'reporter__username', 'details')
    ordering = ('-created_at',)

@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'message', 'verdict', 'confidence_score', 'model_name', 'analyzed_at')
    list_filter = ('verdict', 'model_name', 'analyzed_at')
    search_fields = ('message__message_content', 'message__sender', 'summary')
    ordering = ('-analyzed_at',)