from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import (
    Message,
    Comment,
    UserProfile,
    MessageReport,
    CommentReport,
    ModerationStatus,
    UserProfileReport,
)
from .forms import (
    MessageForm,
    CommentForm,
    ProfileForm,
    UserProfileForm,
    MessageReportForm,
    CommentReportForm,
    UserProfileReportForm,
)
from django.db.models import Q, Count
from django.conf import settings
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.contrib.auth import logout
from django.contrib import messages
from .services.pii_detection import detect_pii
from .services.screenshot_privacy import scan_screenshot_for_pii
from .services.image_moderation import moderate_uploaded_image
from .services.profile_image_moderation import moderate_profile_image
from .services.ai_analysis import analyze_message, save_analysis_result
from .services.similarity import find_similar_messages
from django_ratelimit.decorators import ratelimit
from .services.text_moderation import moderate_text
from .tasks import (
    run_ai_analysis_task,
    run_image_processing_task,
    check_message_processing_timeout_task,
)
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from .services.message_processing import (
    apply_text_only_message_moderation,
    apply_async_image_results_to_overall_moderation,
)
import logging

logger = logging.getLogger(__name__)

def add_ratelimit_message(request, action: str):
    messages.warning(request, get_ratelimit_message(action))


def get_ratelimit_message(action: str) -> str:
    messages_map = {
        "submit_message": "You're submitting messages too quickly. Please wait a bit before trying again.",
        "comment": "You're posting comments too quickly. Please slow down a bit before commenting again.",
        "edit_message": "You're editing messages too quickly. Please wait a moment before making more changes.",
        "edit_comment": "You're editing comments too quickly. Please wait a moment before trying again.",
        "report_message": "You've submitted several reports recently. Please wait before reporting more messages.",
        "report_comment": "You've submitted several reports recently. Please wait before reporting more comments.",
        "report_profile": "You've submitted several reports recently. Please wait before reporting more profiles.",
    }

    return messages_map.get(
        action,
        "You're doing that a bit too quickly. Please wait a moment before trying again."
    )


def apply_message_moderation(message, form):
    field_results = [
        getattr(form, '_message_content_moderation', None),
        getattr(form, '_sender_moderation', None),
        getattr(form, '_platform_moderation', None),
        getattr(form, '_additional_details_moderation', None),
    ]
    field_results = [result for result in field_results if result is not None]

    overall_status = ModerationStatus.APPROVED
    overall_reason_parts = []

    for result in field_results:
        if result.reason:
            overall_reason_parts.append(result.reason)

        if result.status == "rejected":
            overall_status = ModerationStatus.REJECTED
        elif result.status == "pending" and overall_status != ModerationStatus.REJECTED:
            overall_status = ModerationStatus.PENDING

    pii_results = [
        detect_pii(message.message_content, context="message_content", sender=message.sender),
        detect_pii(message.sender, context="sender", sender=message.sender),
        detect_pii(message.platform, context="platform", sender=message.sender),
        detect_pii(message.additional_details, context="additional_details", sender=message.sender),
    ]

    pii_detected = any(result.detected for result in pii_results)
    pii_review_required = any(result.review_required for result in pii_results)

    pii_status = ModerationStatus.APPROVED
    pii_notes_parts = []

    for result in pii_results:
        if result.notes:
            pii_notes_parts.append(result.notes)

        if result.status == "rejected":
            pii_status = ModerationStatus.REJECTED
        elif result.status == "pending" and pii_status != ModerationStatus.REJECTED:
            pii_status = ModerationStatus.PENDING

    message.pii_detected = pii_detected
    message.pii_review_required = pii_review_required
    message.pii_scan_status = pii_status
    message.pii_notes = " | ".join(pii_notes_parts)

    image_reason_parts = []

    if message.screenshot:
        image_mod_result = moderate_uploaded_image(message.screenshot)

        message.image_moderation_status = image_mod_result.moderation_status
        message.image_moderation_reason = image_mod_result.moderation_reason
        message.image_moderation_labels = image_mod_result.moderation_labels

        message.image_relevance_status = image_mod_result.relevance_status
        message.image_relevance_reason = image_mod_result.relevance_reason

        if image_mod_result.moderation_reason:
            image_reason_parts.append(image_mod_result.moderation_reason)

        if image_mod_result.relevance_reason:
            image_reason_parts.append(image_mod_result.relevance_reason)

        if image_mod_result.moderation_status == "rejected":
            overall_status = ModerationStatus.REJECTED
        elif (
            image_mod_result.moderation_status == "pending"
            and overall_status != ModerationStatus.REJECTED
        ):
            overall_status = ModerationStatus.PENDING

        if image_mod_result.relevance_status == "rejected":
            overall_status = ModerationStatus.REJECTED
        elif (
            image_mod_result.relevance_status == "pending"
            and overall_status != ModerationStatus.REJECTED
        ):
            overall_status = ModerationStatus.PENDING

        screenshot_result = scan_screenshot_for_pii(
            message.screenshot,
            sender=message.sender
        )

        if screenshot_result.redacted_image_content:
            message.redacted_screenshot.save(
                screenshot_result.redacted_image_name,
                screenshot_result.redacted_image_content,
                save=False
            )
        else:
            message.redacted_screenshot = None
    else:
        screenshot_result = None
        message.redacted_screenshot = None
        message.image_moderation_status = ModerationStatus.APPROVED
        message.image_moderation_reason = ""
        message.image_moderation_labels = []
        message.image_relevance_status = ModerationStatus.APPROVED
        message.image_relevance_reason = ""

    if screenshot_result and screenshot_result.detected:
        message.pii_detected = True

    if screenshot_result and screenshot_result.notes:
        if message.pii_notes:
            message.pii_notes += " | " + screenshot_result.notes
        else:
            message.pii_notes = screenshot_result.notes

    if screenshot_result and screenshot_result.detected:
        if screenshot_result.redacted_image_content:
            pass
        else:
            message.pii_scan_status = ModerationStatus.PENDING
            message.pii_review_required = True
            if overall_status != ModerationStatus.REJECTED:
                overall_status = ModerationStatus.PENDING

    if pii_status == ModerationStatus.REJECTED:
        overall_status = ModerationStatus.REJECTED
    elif pii_status == ModerationStatus.PENDING and overall_status != ModerationStatus.REJECTED:
        overall_status = ModerationStatus.PENDING

    all_reasons = []
    all_reasons.extend(overall_reason_parts)
    all_reasons.extend(image_reason_parts)
    all_reasons.extend(pii_notes_parts)

    if screenshot_result and screenshot_result.notes:
        all_reasons.append(screenshot_result.notes)

    message.moderation_status = overall_status
    message.moderation_reason = (
        "\n• " + "\n• ".join(all_reasons)
        if all_reasons else ""
    )

    return message


def add_message_submission_feedback(request, message, updated=False):
    reasons = []

    if message.pii_scan_status == ModerationStatus.PENDING:
        reasons.append("possible personal information")

    if message.image_moderation_status == ModerationStatus.PENDING:
        reasons.append("uploaded image content")

    if message.image_relevance_status == ModerationStatus.PENDING:
        reasons.append("image relevance")

    if message.moderation_status == ModerationStatus.REJECTED:
        prefix = "Your updated message was" if updated else "Your message was"
        messages.error(
            request,
            f"{prefix} rejected and could not be posted."
        )
    elif message.moderation_status == ModerationStatus.PENDING:
        prefix = "Your updated message is" if updated else "Your message was"
        if reasons:
            reason_text = ", ".join(reasons)
            messages.warning(
                request,
                f"{prefix} pending review due to {reason_text}."
            )
        else:
            messages.warning(
                request,
                f"{prefix} pending moderator review."
            )
    else:
        if updated:
            messages.success(request, "Your message was updated successfully.")
        else:
            messages.success(request, "Your message was posted successfully.")


def apply_comment_moderation(comment, form):
    moderation_result = getattr(form, '_moderation_result', None)

    if moderation_result:
        comment.moderation_status = moderation_result.status
        comment.moderation_reason = moderation_result.reason
    else:
        comment.moderation_status = ModerationStatus.APPROVED
        comment.moderation_reason = ""

    return comment


def add_comment_submission_feedback(request, comment, updated=False):
    if comment.moderation_status == ModerationStatus.REJECTED:
        prefix = "Your updated comment was" if updated else "Your comment was"
        messages.error(request, f"{prefix} rejected and could not be posted.")
    elif comment.moderation_status == ModerationStatus.PENDING:
        prefix = "Your updated comment is" if updated else "Your comment was"
        messages.warning(
            request,
            f"{prefix} submitted and is now under review. It is only visible to you right now."
        )
    else:
        if updated:
            messages.success(request, "Your comment was updated successfully.")
        else:
            messages.success(request, "Your comment was posted successfully.")


def can_view_message(request, message):
    if message.is_removed:
        return False

    if message.moderation_status == ModerationStatus.APPROVED:
        return True

    if request.user.is_authenticated:
        if request.user == message.user or request.user.is_staff:
            return True

    return False


def can_view_comment(request, comment):
    if comment.is_removed:
        return False

    if comment.moderation_status == ModerationStatus.APPROVED:
        return True

    if request.user.is_authenticated:
        if request.user == comment.user or request.user.is_staff:
            return True

    return False


def message_list(request):
    message_qs = Message.objects.filter(
        is_removed=False,
        moderation_status=ModerationStatus.APPROVED
    ).annotate(
        like_count=Count('likes', distinct=True),
        comment_count=Count('comments', distinct=True)
    )

    query = request.GET.get('q')
    classification = request.GET.get('classification')
    message_type = request.GET.get('message_type')
    platform = request.GET.get('platform')
    sort = request.GET.get('sort', 'newest')

    if query:
        message_qs = message_qs.filter(
            Q(message_content__icontains=query) |
            Q(sender__icontains=query) |
            Q(platform__icontains=query) |
            Q(user__username__icontains=query)
        )

    if classification:
        message_qs = message_qs.filter(classification=classification)

    if message_type:
        message_qs = message_qs.filter(message_type=message_type)

    if platform:
        message_qs = message_qs.filter(platform__icontains=platform)

    if sort == 'oldest':
        message_qs = message_qs.order_by('submission_date')
    elif sort == 'most_liked':
        message_qs = message_qs.order_by('-like_count', '-submission_date')
    elif sort == 'most_commented':
        message_qs = message_qs.order_by('-comment_count', '-submission_date')
    else:
        message_qs = message_qs.order_by('-submission_date')

    paginator = Paginator(message_qs, 10)
    page_number = request.GET.get('page')
    message_page = paginator.get_page(page_number)

    context = {
        'message_page': message_page,
        'query': query or '',
        'selected_classification': classification or '',
        'selected_message_type': message_type or '',
        'selected_platform': platform or '',
        'selected_sort': sort,
    }

    return render(request, 'analyzer/message_list.html', context)


@ratelimit(key='user_or_ip', rate='10/10m', method='POST', block=False)
def message_detail(request, message_id):
    message = get_object_or_404(
        Message,
        id=message_id,
        is_removed=False,
    )

    if (
        request.user.is_authenticated
        and request.user == message.user
        and not message.is_finalized
        and message.processing_status in {"pending", "processing"}
    ):
        return redirect('processing_message', message_id=message.id)

    if not can_view_message(request, message):
        messages.warning(request, "That message is not available.")
        return redirect('message_list')

    all_comments = message.comments.filter(is_removed=False).order_by('-created_at')
    comments_for_view = [comment for comment in all_comments if can_view_comment(request, comment)]

    has_liked_message = False
    if request.user.is_authenticated:
        has_liked_message = request.user in message.likes.all()

    for comment in comments_for_view:
        comment.has_liked = request.user.is_authenticated and request.user in comment.likes.all()

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('account_login')

        if getattr(request, "limited", False):
            add_ratelimit_message(request, "comment")
            return redirect('message_detail', message_id=message.id)

        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.message = message
            comment.user = request.user

            comment = apply_comment_moderation(comment, form)

            if comment.moderation_status == ModerationStatus.REJECTED:
                add_comment_submission_feedback(request, comment, updated=False)
                context = {
                    'message': message,
                    'comments': comments_for_view,
                    'form': form,
                    'has_liked_message': has_liked_message,
                    'similar_messages': [],
                    'is_owner_viewing_pending': (
                        request.user.is_authenticated
                        and request.user == message.user
                        and message.moderation_status == ModerationStatus.PENDING
                    ),
                }
                if message.moderation_status == ModerationStatus.APPROVED:
                    context['similar_messages'] = find_similar_messages(message)
                return render(request, 'analyzer/message_detail.html', context)

            comment.save()

            add_comment_submission_feedback(request, comment, updated=False)
            return redirect('message_detail', message_id=message.id)
    else:
        form = CommentForm()

    similar_messages = []
    if message.moderation_status == ModerationStatus.APPROVED:
        similar_messages = find_similar_messages(message)

    context = {
        'message': message,
        'comments': comments_for_view,
        'form': form,
        'has_liked_message': has_liked_message,
        'similar_messages': similar_messages,
        'is_owner_viewing_pending': (
            request.user.is_authenticated
            and request.user == message.user
            and message.moderation_status == ModerationStatus.PENDING
        ),
    }

    return render(request, 'analyzer/message_detail.html', context)


@login_required
@ratelimit(key='user_or_ip', rate='5/20m', method='POST', block=False)
def submit_message(request):
    if request.method == 'POST':
        if getattr(request, "limited", False):
            add_ratelimit_message(request, "submit_message")
            return redirect('submit_message')

        form = MessageForm(request.POST, request.FILES)
        if form.is_valid():
            message = form.save(commit=False)
            message.user = request.user
            message.processing_status = "pending"
            message.processing_error = ""
            message.is_finalized = False

            message.moderation_status = ModerationStatus.PENDING
            message.moderation_reason = "Processing submission..."
            message.save()
            
            run_ai_analysis_task(message.id)
            run_image_processing_task(message.id)
            
            check_message_processing_timeout_task.schedule(
                args=(message.id,),
                delay=getattr(settings, "MESSAGE_PROCESSING_TIMEOUT_SECONDS", 180)
            )

            return redirect('processing_message', message_id=message.id)
    else:
        form = MessageForm()

    return render(request, 'analyzer/submit_message.html', {'form': form})

@login_required
def processing_message(request, message_id):
    message = get_object_or_404(
        Message,
        id=message_id,
        user=request.user,
        is_removed=False,
    )

    if message.is_finalized or message.processing_status == "completed":
        return redirect('message_detail', message_id=message.id)

    return render(request, 'analyzer/processing_message.html', {
        'message': message,
    })


@login_required
def message_processing_status(request, message_id):
    message = get_object_or_404(
        Message,
        id=message_id,
        user=request.user,
        is_removed=False,
    )

    ready = (
        message.processing_status == "completed"
        and message.is_finalized
    )

    failed = message.processing_status == "failed"

    return JsonResponse({
        "ready": ready,
        "failed": failed,
        "ai_status": message.ai_status,
        "image_processing_status": message.image_processing_status,
        "processing_status": message.processing_status,
        "processing_error": message.processing_error,
        "redirect_url": reverse('message_detail', args=[message.id]) if ready else "",
        "message_id": message.id,
    })

@login_required
def retry_message_processing(request, message_id):
    message = get_object_or_404(
        Message,
        id=message_id,
        user=request.user,
        is_removed=False,
    )

    if message.processing_status != "failed":
        return redirect('message_detail', message_id=message.id)

    # reset state
    message.processing_status = "pending"
    message.processing_error = ""
    message.is_finalized = False
    message.ai_status = "pending"
    message.image_processing_status = "pending"
    message.processing_completed_at = None
    message.save()

    run_ai_analysis_task(message.id)
    run_image_processing_task(message.id)
    check_message_processing_timeout_task.schedule(
        args=(message.id,),
        delay=getattr(settings, "MESSAGE_PROCESSING_TIMEOUT_SECONDS", 180)
    )

    return redirect('processing_message', message_id=message.id)

@login_required
@ratelimit(key='user_or_ip', rate='10/10m', method='POST', block=False)
def edit_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)

    if message.user != request.user:
        return redirect('message_list')

    if request.method == 'POST':
        if getattr(request, "limited", False):
            add_ratelimit_message(request, "edit_message")
            return redirect('edit_message', message_id=message.id)

        form = MessageForm(request.POST, request.FILES, instance=message)
        if form.is_valid():
            updated_message = form.save(commit=False)
            updated_message.user = request.user

            updated_message = apply_message_moderation(updated_message, form)

            if updated_message.moderation_status == ModerationStatus.REJECTED:
                add_message_submission_feedback(request, updated_message, updated=True)
                return render(
                    request,
                    'analyzer/edit_message.html',
                    {'form': form, 'message': message}
                )

            updated_message.save()

            try:
                analysis_data = analyze_message(updated_message)
                save_analysis_result(updated_message, analysis_data)
            except Exception:
                logger.exception(
                    "AI analysis failed during edit_message for message %s",
                    updated_message.id
                )

            add_message_submission_feedback(request, updated_message, updated=True)
            return redirect('message_detail', message_id=updated_message.id)
    else:
        form = MessageForm(instance=message)

    return render(request, 'analyzer/edit_message.html', {'form': form, 'message': message})


@login_required
def delete_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)

    if message.user != request.user:
        return redirect('message_list')

    if request.method == 'POST':
        message.delete()
        messages.success(request, "Your message was deleted successfully.")
        return redirect('message_list')

    return render(request, 'analyzer/delete_message.html', {'message': message})


@login_required
@ratelimit(key='user_or_ip', rate='10/10m', method='POST', block=False)
def edit_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)

    if comment.user != request.user:
        return redirect('message_detail', message_id=comment.message.id)

    if request.method == 'POST':
        if getattr(request, "limited", False):
            add_ratelimit_message(request, "edit_comment")
            return redirect('edit_comment', comment_id=comment.id)

        form = CommentForm(request.POST, instance=comment)
        if form.is_valid():
            updated_comment = form.save(commit=False)
            updated_comment.user = request.user
            updated_comment.message = comment.message

            updated_comment = apply_comment_moderation(updated_comment, form)

            if updated_comment.moderation_status == ModerationStatus.REJECTED:
                add_comment_submission_feedback(request, updated_comment, updated=True)
                return render(
                    request,
                    'analyzer/edit_comment.html',
                    {'form': form, 'comment': comment}
                )

            updated_comment.save()

            add_comment_submission_feedback(request, updated_comment, updated=True)
            return redirect('message_detail', message_id=comment.message.id)
    else:
        form = CommentForm(instance=comment)

    return render(request, 'analyzer/edit_comment.html', {'form': form, 'comment': comment})


@login_required
def delete_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)

    if comment.user != request.user:
        return redirect('message_detail', message_id=comment.message.id)

    if request.method == 'POST':
        message_id = comment.message.id
        comment.delete()
        messages.success(request, "Your comment was deleted successfully.")
        return redirect('message_detail', message_id=message_id)

    return render(request, 'analyzer/delete_comment.html', {'comment': comment})


@login_required
def toggle_message_like(request, message_id):
    if request.method != 'POST':
        return redirect('message_detail', message_id=message_id)

    message = get_object_or_404(Message, id=message_id)

    if request.user in message.likes.all():
        message.likes.remove(request.user)
    else:
        message.likes.add(request.user)

    return redirect('message_detail', message_id=message.id)


@login_required
def toggle_comment_like(request, comment_id):
    if request.method != 'POST':
        return redirect('message_list')

    comment = get_object_or_404(Comment, id=comment_id)

    if request.user in comment.likes.all():
        comment.likes.remove(request.user)
    else:
        comment.likes.add(request.user)

    return redirect('message_detail', message_id=comment.message.id)


@login_required
def profile_view(request):
    profile_user = request.user
    profile, created = UserProfile.objects.get_or_create(user=profile_user)

    message_count = Message.objects.filter(user=profile_user).count()
    comment_count = Comment.objects.filter(user=profile_user).count()

    message_likes_received = 0
    submitted_messages = Message.objects.filter(user=profile_user)
    for message in submitted_messages:
        message_likes_received += message.likes.count()

    comment_likes_received = 0
    user_comments = Comment.objects.filter(user=profile_user)
    for comment in user_comments:
        comment_likes_received += comment.likes.count()

    context = {
        'profile_user': profile_user,
        'profile': profile,
        'message_count': message_count,
        'comment_count': comment_count,
        'message_likes_received': message_likes_received,
        'comment_likes_received': comment_likes_received,
    }

    return render(request, 'analyzer/profile.html', context)


@login_required
def edit_profile(request):
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        user_form = ProfileForm(request.POST, instance=request.user)
        profile_form = UserProfileForm(request.POST, request.FILES, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            uploaded_profile_image = profile_form.cleaned_data.get('profile_image')

            image_result = moderate_profile_image(uploaded_profile_image)

            if not image_result.allowed:
                profile_form.add_error('profile_image', image_result.reason)
            else:
                user_form.save()

                profile = profile_form.save(commit=False)

                bio_result = getattr(profile_form, '_bio_moderation_result', None)
                if bio_result:
                    profile.moderation_status = bio_result.status
                    profile.moderation_reason = bio_result.reason

                profile.save()

                messages.success(request, "Your profile was updated successfully.")
                return redirect('profile')
    else:
        user_form = ProfileForm(instance=request.user)
        profile_form = UserProfileForm(instance=profile)

    return render(request, 'analyzer/edit_profile.html', {
        'form': user_form,
        'profile_form': profile_form,
    })


def user_messages(request, username):
    user = get_object_or_404(User, username=username)
    profile, created = UserProfile.objects.get_or_create(user=user)

    if request.user.is_authenticated and request.user == user:
        user_posts = Message.objects.filter(
            user=user,
            is_removed=False,
        ).exclude(moderation_status=ModerationStatus.REJECTED).order_by('-submission_date')
    elif request.user.is_authenticated and request.user.is_staff:
        user_posts = Message.objects.filter(
            user=user,
            is_removed=False,
        ).order_by('-submission_date')
    else:
        user_posts = Message.objects.filter(
            user=user,
            is_removed=False,
            moderation_status=ModerationStatus.APPROVED
        ).order_by('-submission_date')

    context = {
        'profile_user': user,
        'profile': profile,
        'user_posts': user_posts
    }

    return render(request, 'analyzer/user_messages.html', context)


@login_required
def delete_account(request):
    if request.method == 'POST':
        user = request.user
        logout(request)
        user.delete()
        messages.success(request, "Your account was deleted successfully.")
        return redirect('message_list')

    return render(request, 'analyzer/delete_account.html')


@login_required
@ratelimit(key='user_or_ip', rate='10/h', method='POST', block=False)
def report_message(request, message_id):
    message = get_object_or_404(Message, id=message_id, is_removed=False)

    existing_report = MessageReport.objects.filter(message=message, reporter=request.user).first()
    if existing_report:
        messages.info(request, "You have already reported this message.")
        return redirect('message_detail', message_id=message.id)

    if request.method == 'POST':
        if getattr(request, "limited", False):
            add_ratelimit_message(request, "report_message")
            return redirect('message_detail', message_id=message.id)

        form = MessageReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.message = message
            report.reporter = request.user
            report.save()

            message.is_flagged = True
            message.save()

            messages.success(request, "This message has been reported for moderator review.")
            return redirect('message_detail', message_id=message.id)
    else:
        form = MessageReportForm()

    return render(request, 'analyzer/report_message.html', {
        'form': form,
        'message': message,
    })


@login_required
@ratelimit(key='user_or_ip', rate='10/h', method='POST', block=False)
def report_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id, is_removed=False)

    existing_report = CommentReport.objects.filter(comment=comment, reporter=request.user).first()
    if existing_report:
        messages.info(request, "You have already reported this comment.")
        return redirect('message_detail', message_id=comment.message.id)

    if request.method == 'POST':
        if getattr(request, "limited", False):
            add_ratelimit_message(request, "report_comment")
            return redirect('message_detail', message_id=comment.message.id)

        form = CommentReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.comment = comment
            report.reporter = request.user
            report.save()

            comment.is_flagged = True
            comment.save()

            messages.success(request, "This comment has been reported for moderator review.")
            return redirect('message_detail', message_id=comment.message.id)
    else:
        form = CommentReportForm()

    return render(request, 'analyzer/report_comment.html', {
        'form': form,
        'comment': comment,
    })


@login_required
@ratelimit(key='user', rate='10/h', method='POST', block=False)
def report_profile(request, username):
    profile_user = get_object_or_404(User, username=username)
    profile = get_object_or_404(UserProfile, user=profile_user)

    existing_report = UserProfileReport.objects.filter(
        profile=profile,
        reporter=request.user
    ).first()

    if existing_report:
        messages.info(request, "You have already reported this profile.")
        return redirect('user_messages', username=profile_user.username)

    if request.method == 'POST':
        if getattr(request, "limited", False):
            add_ratelimit_message(request, "report_profile")
            return redirect('user_messages', username=profile_user.username)

        form = UserProfileReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.profile = profile
            report.reporter = request.user
            report.save()

            messages.success(request, "This profile has been reported for moderator review.")
            return redirect('user_messages', username=profile_user.username)
    else:
        form = UserProfileReportForm()

    return render(request, 'analyzer/report_profile.html', {
        'form': form,
        'profile_user': profile_user,
        'profile': profile,
    })