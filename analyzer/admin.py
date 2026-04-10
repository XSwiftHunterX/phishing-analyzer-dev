from django.contrib import admin, messages
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html, conditional_escape
from django.utils.safestring import mark_safe
from django.urls import reverse

from .models import (
    Message,
    Comment,
    UserProfile,
    MessageReport,
    CommentReport,
    UserProfileReport,
    AIAnalysis,
)
from .services.message_processing import (
    reset_message_processing_state,
    queue_message_processing,
)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'message_type',
        'platform',
        'classification',
        'user',
        'submission_date',
        'processing_status_badge',
        'moderation_status_badge',
        'ai_status',
        'image_processing_status',
        'duplicate_submission_suspected',
        'has_image_issue',
        'has_pii_issue',
        'is_reported',
        'status_flags',
    )
    list_filter = (
        'processing_status',
        'processing_failure_type',
        'is_finalized',
        'ai_status',
        'image_processing_status',
        'moderation_status',
        'duplicate_submission_suspected',
        'is_flagged',
        'message_type',
        'classification',
        'pii_scan_status',
        'image_moderation_status',
        'image_relevance_status',
    )
    search_fields = ('message_content', 'sender', 'platform', 'user__username')
    ordering = ('-submission_date',)
    actions = [
        'approve_selected_messages',
        'reject_selected_messages',
        'mark_pending_review',
        'clear_flag_on_selected',
        'mark_duplicate_suspected',
        'retry_failed_messages',
    ]

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
                'is_flagged',
                'duplicate_submission_suspected',
                'is_removed',
            )
        }),
        ('Processing Info', {
            'fields': (
                'processing_status',
                'processing_failure_type',
                'processing_error',
                'is_finalized',
                'ai_status',
                'image_processing_status',
                'processing_started_at',
                'processing_completed_at',
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
        'processing_status',
        'processing_failure_type',
        'processing_error',
        'is_finalized',
        'ai_status',
        'image_processing_status',
        'processing_started_at',
        'processing_completed_at',
    )

    def save_model(self, request, obj, form, change):
        if change:
            original = Message.objects.get(pk=obj.pk)

            admin_approved_failed_message = (
                original.processing_status == "failed"
                and obj.moderation_status == "approved"
            )

            if admin_approved_failed_message:
                obj.processing_status = "completed"
                obj.is_finalized = True
                obj.processing_error = ""
                obj.processing_failure_type = "admin_override"
                obj.processing_completed_at = timezone.now()

        super().save_model(request, obj, form, change)

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

    @admin.display(description='Processing')
    def processing_status_badge(self, obj):
        colors = {
            'pending': '#ffc107',
            'processing': '#0d6efd',
            'completed': '#198754',
            'failed': '#dc3545',
        }
        color = colors.get(obj.processing_status, '#6c757d')
        return format_html(
            '<span style="background:{}; color:white; padding:4px 8px; border-radius:999px; font-weight:600;">{}</span>',
            color,
            obj.processing_status.title(),
        )

    @admin.display(description='Moderation')
    def moderation_status_badge(self, obj):
        colors = {
            'approved': '#198754',
            'pending': '#ffc107',
            'rejected': '#dc3545',
        }
        color = colors.get(obj.moderation_status, '#6c757d')
        return format_html(
            '<span style="background:{}; color:white; padding:4px 8px; border-radius:999px; font-weight:600;">{}</span>',
            color,
            obj.moderation_status.title(),
        )

    @admin.action(description="Approve selected messages")
    def approve_selected_messages(self, request, queryset):
        updated = queryset.update(moderation_status='approved')
        self.message_user(request, f"{updated} message(s) marked as approved.", level=messages.SUCCESS)

    @admin.action(description="Reject selected messages")
    def reject_selected_messages(self, request, queryset):
        updated = queryset.update(moderation_status='rejected', is_flagged=True)
        self.message_user(request, f"{updated} message(s) marked as rejected.", level=messages.WARNING)

    @admin.action(description="Mark selected messages as pending review")
    def mark_pending_review(self, request, queryset):
        updated = queryset.update(moderation_status='pending', is_flagged=True)
        self.message_user(request, f"{updated} message(s) marked as pending review.", level=messages.INFO)

    @admin.action(description="Clear flag on selected messages")
    def clear_flag_on_selected(self, request, queryset):
        updated = queryset.update(is_flagged=False)
        self.message_user(request, f"{updated} message(s) had flags cleared.", level=messages.SUCCESS)

    @admin.action(description="Mark selected messages as possible duplicates")
    def mark_duplicate_suspected(self, request, queryset):
        updated = queryset.update(duplicate_submission_suspected=True)
        self.message_user(request, f"{updated} message(s) marked as duplicate-suspected.", level=messages.WARNING)

    @admin.action(description="Retry processing for selected failed messages")
    def retry_failed_messages(self, request, queryset):
        retried_count = 0

        for message in queryset:
            if message.processing_status != "failed":
                continue

            message = reset_message_processing_state(message)
            message.save()
            queue_message_processing(message)
            retried_count += 1

        self.message_user(
            request,
            f"{retried_count} failed message(s) were requeued for processing."
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
    
    @admin.display(description='Flags')
    def status_flags(self, obj):
        flags = []

        if obj.processing_status == 'failed':
            flags.append('<span style="color:#dc3545; font-weight:600;">FAILED</span>')

        if obj.moderation_status == 'pending':
            flags.append('<span style="color:#ffc107; font-weight:600;">PENDING</span>')

        if obj.is_flagged:
            flags.append('<span style="color:#fd7e14; font-weight:600;">FLAGGED</span>')

        if obj.duplicate_submission_suspected:
            flags.append('<span style="color:#6f42c1; font-weight:600;">DUPLICATE</span>')

        if obj.pii_detected:
            flags.append('<span style="color:#0dcaf0; font-weight:600;">PII</span>')

        if not flags:
            return format_html('<span style="color:#198754;">OK</span>')

        return mark_safe(' | '.join(flags))


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'message_link',
        'created_at',
        'moderation_status',
        'is_flagged',
    )
    list_filter = ('moderation_status', 'is_flagged', 'created_at')
    search_fields = ('content', 'user__username', 'message__message_content')
    ordering = ('-created_at',)
    actions = ['approve_comments', 'reject_comments']

    fieldsets = (
        ('Comment Info', {
            'fields': ('message', 'user', 'content', 'created_at')
        }),
        ('Moderation', {
            'fields': (
                'moderation_status',
                'moderation_reason',
                'is_flagged',
            )
        }),
    )

    readonly_fields = ('created_at',)

    @admin.display(description='Message')
    def message_link(self, obj):
        url = reverse('admin:analyzer_message_change', args=[obj.message.id])
        return format_html('<a href="{}">Message #{}</a>', url, obj.message.id)

    @admin.action(description="Approve selected comments")
    def approve_comments(self, request, queryset):
        updated = queryset.update(moderation_status='approved', is_flagged=False)
        self.message_user(request, f"{updated} comment(s) approved.", level=messages.SUCCESS)

    @admin.action(description="Reject selected comments")
    def reject_comments(self, request, queryset):
        updated = queryset.update(moderation_status='rejected', is_flagged=True)
        self.message_user(request, f"{updated} comment(s) rejected.", level=messages.WARNING)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'moderation_status',
        'rate_limited_flag',
        'duplicate_abuse_flag',
        'flagged_at',
    )
    list_filter = (
        'moderation_status',
        'rate_limited_flag',
        'duplicate_abuse_flag',
        'flagged_at',
    )
    search_fields = ('user__username', 'user__email', 'admin_flag_notes')
    actions = ['mark_rate_limited', 'mark_duplicate_abuse', 'clear_account_flags']

    fieldsets = (
        ('User Info', {
            'fields': ('user', 'bio', 'profile_image')
        }),
        ('Profile Moderation', {
            'fields': (
                'moderation_status',
                'moderation_reason',
            )
        }),
        ('Account Flags', {
            'fields': (
                'rate_limited_flag',
                'duplicate_abuse_flag',
                'flagged_at',
                'admin_flag_notes',
            )
        }),
    )

    @admin.action(description="Flag selected profiles for rate limiting")
    def mark_rate_limited(self, request, queryset):
        updated = queryset.update(
            rate_limited_flag=True,
            flagged_at=timezone.now(),
        )
        self.message_user(request, f"{updated} profile(s) flagged for rate limiting.")

    @admin.action(description="Flag selected profiles for duplicate abuse")
    def mark_duplicate_abuse(self, request, queryset):
        updated = queryset.update(
            duplicate_abuse_flag=True,
            flagged_at=timezone.now(),
        )
        self.message_user(request, f"{updated} profile(s) flagged for duplicate abuse.")

    @admin.action(description="Clear account flags on selected profiles")
    def clear_account_flags(self, request, queryset):
        updated = queryset.update(
            rate_limited_flag=False,
            duplicate_abuse_flag=False,
            admin_flag_notes="",
        )
        self.message_user(request, f"{updated} profile(s) had account flags cleared.")

    @admin.display(boolean=True, description='User Rate-Limited')
    def user_rate_limited(self, obj):
        return hasattr(obj.user, 'userprofile') and obj.user.userprofile.rate_limited_flag

    @admin.display(boolean=True, description='User Duplicate Flag')
    def user_duplicate_flag(self, obj):
        return hasattr(obj.user, 'userprofile') and obj.user.userprofile.duplicate_abuse_flag


@admin.register(MessageReport)
class MessageReportAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'message_link',
        'reporter',
        'reason',
        'created_at',
        'is_reviewed',
    )
    list_filter = ('reason', 'is_reviewed', 'created_at')
    search_fields = ('message__message_content', 'reporter__username', 'details')
    ordering = ('-created_at',)
    actions = ['mark_reviewed', 'mark_unreviewed']

    @admin.display(description='Reported Message')
    def message_link(self, obj):
        url = reverse('admin:analyzer_message_change', args=[obj.message.id])
        return format_html('<a href="{}">Message #{}</a>', url, obj.message.id)

    @admin.action(description="Mark selected reports as reviewed")
    def mark_reviewed(self, request, queryset):
        updated = queryset.update(is_reviewed=True)
        self.message_user(request, f"{updated} report(s) marked reviewed.", level=messages.SUCCESS)

    @admin.action(description="Mark selected reports as unreviewed")
    def mark_unreviewed(self, request, queryset):
        updated = queryset.update(is_reviewed=False)
        self.message_user(request, f"{updated} report(s) marked unreviewed.", level=messages.INFO)


@admin.register(CommentReport)
class CommentReportAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'comment_link',
        'message_link',
        'reporter',
        'reason',
        'created_at',
        'is_reviewed',
    )
    list_filter = ('reason', 'is_reviewed', 'created_at')
    search_fields = ('comment__content', 'reporter__username', 'details')
    ordering = ('-created_at',)
    actions = ['mark_reviewed', 'mark_unreviewed']

    @admin.display(description='Reported Comment')
    def comment_link(self, obj):
        url = reverse('admin:analyzer_comment_change', args=[obj.comment.id])
        return format_html('<a href="{}">Comment #{}</a>', url, obj.comment.id)

    @admin.display(description='On Message')
    def message_link(self, obj):
        url = reverse('admin:analyzer_message_change', args=[obj.comment.message.id])
        return format_html('<a href="{}">Message #{}</a>', url, obj.comment.message.id)

    @admin.action(description="Mark selected reports as reviewed")
    def mark_reviewed(self, request, queryset):
        updated = queryset.update(is_reviewed=True)
        self.message_user(request, f"{updated} report(s) marked reviewed.", level=messages.SUCCESS)

    @admin.action(description="Mark selected reports as unreviewed")
    def mark_unreviewed(self, request, queryset):
        updated = queryset.update(is_reviewed=False)
        self.message_user(request, f"{updated} report(s) marked unreviewed.", level=messages.INFO)


@admin.register(UserProfileReport)
class UserProfileReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'profile', 'reporter', 'reason', 'created_at', 'is_reviewed')
    list_filter = ('reason', 'is_reviewed', 'created_at')
    search_fields = ('profile__user__username', 'reporter__username', 'details')
    ordering = ('-created_at',)
    actions = ['mark_reviewed', 'mark_unreviewed']

    @admin.action(description="Mark selected reports as reviewed")
    def mark_reviewed(self, request, queryset):
        updated = queryset.update(is_reviewed=True)
        self.message_user(request, f"{updated} report(s) marked reviewed.", level=messages.SUCCESS)

    @admin.action(description="Mark selected reports as unreviewed")
    def mark_unreviewed(self, request, queryset):
        updated = queryset.update(is_reviewed=False)
        self.message_user(request, f"{updated} report(s) marked unreviewed.", level=messages.INFO)


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'message_link', 'verdict', 'confidence_score', 'model_name', 'analyzed_at')
    list_filter = ('verdict', 'model_name', 'analyzed_at')
    search_fields = ('message__message_content', 'message__sender', 'summary')
    ordering = ('-analyzed_at',)

    @admin.display(description='Message')
    def message_link(self, obj):
        url = reverse('admin:analyzer_message_change', args=[obj.message.id])
        return format_html('<a href="{}">Message #{}</a>', url, obj.message.id)