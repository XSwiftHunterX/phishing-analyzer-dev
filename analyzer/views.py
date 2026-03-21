from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Message, Comment, UserProfile, MessageReport, CommentReport, ModerationStatus
from .forms import (
    MessageForm, CommentForm, ProfileForm, UserProfileForm,
    MessageReportForm, CommentReportForm
)
from django.db.models import Q, Count
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.contrib.auth import logout
from django.contrib import messages
from .services.pii_detection import detect_pii
from .services.screenshot_privacy import scan_screenshot_for_pii
from .services.image_moderation import moderate_uploaded_image
from .services.profile_image_moderation import moderate_profile_image

# Create your views here.
def message_list(request):
    messages = Message.objects.filter(
        is_removed=False,
        moderation_status=ModerationStatus.APPROVED
    ).annotate(
        like_count=Count('likes', distinct=True),
        comment_count=Count('comments', distinct=True)
    )

    query = request.GET.get('q')
    classification = request.GET.get('classification')
    suspected_risk = request.GET.get('suspected_risk')
    message_type = request.GET.get('message_type')
    sort = request.GET.get('sort', 'newest')

    if query:
        messages = messages.filter(
            Q(message_content__icontains=query) |
            Q(sender__icontains=query) |
            Q(user__username__icontains=query)
        )

    if classification:
        messages = messages.filter(classification=classification)

    if suspected_risk:
        messages = messages.filter(suspected_risk=suspected_risk)

    if message_type:
        messages = messages.filter(message_type=message_type)

    if sort == 'oldest':
        messages = messages.order_by('submission_date')
    elif sort == 'most_liked':
        messages = messages.order_by('-like_count', '-submission_date')
    elif sort == 'most_commented':
        messages = messages.order_by('-comment_count', '-submission_date')
    else:
        messages = messages.order_by('-submission_date')

    paginator = Paginator(messages, 10)
    page_number = request.GET.get('page')
    message_page = paginator.get_page(page_number)

    context = {
        'message_page': message_page,
        'query': query or '',
        'selected_classification': classification or '',
        'selected_suspected_risk': suspected_risk or '',
        'selected_message_type': message_type or '',
        'selected_sort': sort,
    }

    return render(request, 'analyzer/message_list.html', context)

def message_detail(request, message_id):
    message = get_object_or_404(
        Message,
        id=message_id,
        is_removed=False,
        moderation_status=ModerationStatus.APPROVED
    )
    comments = message.comments.filter(
        is_removed=False,
        moderation_status=ModerationStatus.APPROVED
    ).order_by('-created_at')

    has_liked_message = False
    if request.user.is_authenticated:
        has_liked_message = request.user in message.likes.all()

    for comment in comments:
        comment.has_liked = request.user.is_authenticated and request.user in comment.likes.all()

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('account_login')
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.message = message
            comment.user = request.user

            moderation_result = getattr(form, '_moderation_result', None)
            if moderation_result:
                comment.moderation_status = moderation_result.status
                comment.moderation_reason = moderation_result.reason
                comment.moderation_score = moderation_result.score
                comment.requires_human_review = moderation_result.requires_human_review

            comment.save()

            if comment.moderation_status == ModerationStatus.PENDING:
                messages.success(request, "Your comment was submitted and is pending moderator review.")
            else:
                messages.success(request, "Your comment was posted successfully.")

            return redirect('message_detail', message_id=message.id)
    else:
        form = CommentForm()

    context = {
        'message': message,
        'comments': comments,
        'form': form,
        'has_liked_message': has_liked_message,
    }

    return render(request, 'analyzer/message_detail.html', context)

@login_required
def submit_message(request):
    if request.method == 'POST':
        form = MessageForm(request.POST, request.FILES)
        if form.is_valid():
            message = form.save(commit=False)
            message.user = request.user

            field_results = [
                getattr(form, '_message_content_moderation', None),
                getattr(form, '_sender_moderation', None),
                getattr(form, '_additional_details_moderation', None),
            ]
            field_results = [result for result in field_results if result is not None]

            overall_status = ModerationStatus.APPROVED
            overall_reason_parts = []
            overall_score = 0.0
            requires_human_review = False

            for result in field_results:
                if result.reason:
                    overall_reason_parts.append(result.reason)

                overall_score = max(overall_score, result.score)

                if result.requires_human_review:
                    requires_human_review = True

                if result.status == "pending":
                    overall_status = ModerationStatus.PENDING

            message.moderation_status = overall_status
            message.moderation_reason = " | ".join(overall_reason_parts)
            message.moderation_score = overall_score
            message.requires_human_review = requires_human_review

            pii_results = [
                detect_pii(message.message_content, context="message_content", sender=message.sender),
                detect_pii(message.sender, context="sender", sender=message.sender),
                detect_pii(message.additional_details, context="additional_details", sender=message.sender),
            ]

            pii_detected = any(result.detected for result in pii_results)
            pii_review_required = any(result.review_required for result in pii_results)

            pii_status = ModerationStatus.APPROVED
            pii_notes_parts = []

            for result in pii_results:
                if result.notes:
                    pii_notes_parts.append(result.notes)

                if result.status == "pending":
                    pii_status = ModerationStatus.PENDING

            message.pii_detected = pii_detected
            message.pii_review_required = pii_review_required
            message.pii_scan_status = pii_status
            message.pii_notes = " | ".join(pii_notes_parts)

            if message.screenshot:
                image_mod_result = moderate_uploaded_image(message.screenshot)

                message.image_moderation_status = image_mod_result.moderation_status
                message.image_moderation_reason = image_mod_result.moderation_reason
                message.image_moderation_labels = image_mod_result.moderation_labels

                message.image_relevance_status = image_mod_result.relevance_status
                message.image_relevance_reason = image_mod_result.relevance_reason

                if image_mod_result.moderation_status == "pending":
                    message.requires_human_review = True
                    if message.moderation_status == ModerationStatus.APPROVED:
                        message.moderation_status = ModerationStatus.PENDING

                if image_mod_result.relevance_status == "pending":
                    message.requires_human_review = True
                    if message.moderation_status == ModerationStatus.APPROVED:
                        message.moderation_status = ModerationStatus.PENDING

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
                    # Screenshot PII was successfully redacted, so do not force pending
                    pass
                else:
                    message.pii_scan_status = ModerationStatus.PENDING
                    message.pii_review_required = True
                    message.requires_human_review = True
                    if message.moderation_status == ModerationStatus.APPROVED:
                        message.moderation_status = ModerationStatus.PENDING

            if pii_status == ModerationStatus.PENDING:
                message.requires_human_review = True
                if message.moderation_status == ModerationStatus.APPROVED:
                    message.moderation_status = ModerationStatus.PENDING

            message.save()

            if message.pii_scan_status == ModerationStatus.PENDING:
                messages.success(
                    request,
                    "Your message was submitted and is pending review because possible personal information was detected."
                )
            elif message.image_moderation_status == ModerationStatus.PENDING:
                messages.success(
                    request,
                    "Your message was submitted and is pending review because the uploaded image may contain inappropriate content."
                )
            elif message.image_relevance_status == ModerationStatus.PENDING:
                messages.success(
                    request,
                    "Your message was submitted and is pending review because the uploaded image may not be related to a phishing or scam message."
                )
            elif message.moderation_status == ModerationStatus.PENDING:
                messages.success(request, "Your message was submitted and is pending moderator review.")
            else:
                messages.success(request, "Your message was posted successfully.")

            return redirect('message_list')
    else:
        form = MessageForm()

    return render(request, 'analyzer/submit_message.html', {'form': form})

@login_required
def edit_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)

    if message.user != request.user:
        return redirect('message_list')

    if request.method == 'POST':
        form = MessageForm(request.POST, request.FILES, instance=message)
        if form.is_valid():
            updated_message = form.save(commit=False)
            updated_message.user = request.user

            field_results = [
                getattr(form, '_message_content_moderation', None),
                getattr(form, '_sender_moderation', None),
                getattr(form, '_additional_details_moderation', None),
            ]
            field_results = [result for result in field_results if result is not None]

            overall_status = ModerationStatus.APPROVED
            overall_reason_parts = []
            overall_score = 0.0
            requires_human_review = False

            for result in field_results:
                if result.reason:
                    overall_reason_parts.append(result.reason)

                overall_score = max(overall_score, result.score)

                if result.requires_human_review:
                    requires_human_review = True

                if result.status == "pending":
                    overall_status = ModerationStatus.PENDING

            updated_message.moderation_status = overall_status
            updated_message.moderation_reason = " | ".join(overall_reason_parts)
            updated_message.moderation_score = overall_score
            updated_message.requires_human_review = requires_human_review

            pii_results = [
                detect_pii(updated_message.message_content, context="message_content", sender=updated_message.sender),
                detect_pii(updated_message.sender, context="sender", sender=updated_message.sender),
                detect_pii(updated_message.additional_details, context="additional_details", sender=updated_message.sender),
            ]

            pii_detected = any(result.detected for result in pii_results)
            pii_review_required = any(result.review_required for result in pii_results)

            pii_status = ModerationStatus.APPROVED
            pii_notes_parts = []

            for result in pii_results:
                if result.notes:
                    pii_notes_parts.append(result.notes)

                if result.status == "pending":
                    pii_status = ModerationStatus.PENDING

            updated_message.pii_detected = pii_detected
            updated_message.pii_review_required = pii_review_required
            updated_message.pii_scan_status = pii_status
            updated_message.pii_notes = " | ".join(pii_notes_parts)

            if updated_message.screenshot:
                image_mod_result = moderate_uploaded_image(updated_message.screenshot)

                updated_message.image_moderation_status = image_mod_result.moderation_status
                updated_message.image_moderation_reason = image_mod_result.moderation_reason
                updated_message.image_moderation_labels = image_mod_result.moderation_labels

                updated_message.image_relevance_status = image_mod_result.relevance_status
                updated_message.image_relevance_reason = image_mod_result.relevance_reason

                if image_mod_result.moderation_status == "pending":
                    updated_message.requires_human_review = True
                    if updated_message.moderation_status == ModerationStatus.APPROVED:
                        updated_message.moderation_status = ModerationStatus.PENDING

                if image_mod_result.relevance_status == "pending":
                    updated_message.requires_human_review = True
                    if updated_message.moderation_status == ModerationStatus.APPROVED:
                        updated_message.moderation_status = ModerationStatus.PENDING

                screenshot_result = scan_screenshot_for_pii(
                    updated_message.screenshot,
                    sender=updated_message.sender
                )

                if screenshot_result.redacted_image_content:
                    updated_message.redacted_screenshot.save(
                        screenshot_result.redacted_image_name,
                        screenshot_result.redacted_image_content,
                        save=False
                    )
                else:
                    updated_message.redacted_screenshot = None
            else:
                screenshot_result = None
                updated_message.redacted_screenshot = None
                updated_message.image_moderation_status = ModerationStatus.APPROVED
                updated_message.image_moderation_reason = ""
                updated_message.image_moderation_labels = []
                updated_message.image_relevance_status = ModerationStatus.APPROVED
                updated_message.image_relevance_reason = ""

            if screenshot_result and screenshot_result.detected:
                updated_message.pii_detected = True

            if screenshot_result and screenshot_result.notes:
                if updated_message.pii_notes:
                    updated_message.pii_notes += " | " + screenshot_result.notes
                else:
                    updated_message.pii_notes = screenshot_result.notes

            if screenshot_result and screenshot_result.detected:
                if screenshot_result.redacted_image_content:
                    # Screenshot PII was successfully redacted, so do not force pending
                    pass
                else:
                    updated_message.pii_scan_status = ModerationStatus.PENDING
                    updated_message.pii_review_required = True
                    updated_message.requires_human_review = True
                    if updated_message.moderation_status == ModerationStatus.APPROVED:
                        updated_message.moderation_status = ModerationStatus.PENDING

            if pii_status == ModerationStatus.PENDING:
                updated_message.requires_human_review = True
                if updated_message.moderation_status == ModerationStatus.APPROVED:
                    updated_message.moderation_status = ModerationStatus.PENDING

            updated_message.save()

            if updated_message.pii_scan_status == ModerationStatus.PENDING:
                messages.success(
                    request,
                    "Your updated message was submitted and is pending review because possible personal information was detected."
                )
                return redirect('message_list')
            elif updated_message.image_moderation_status == ModerationStatus.PENDING:
                messages.success(
                    request,
                    "Your updated message was submitted and is pending review because the uploaded image may contain inappropriate content."
                )
                return redirect('message_list')
            elif updated_message.image_relevance_status == ModerationStatus.PENDING:
                messages.success(
                    request,
                    "Your updated message was submitted and is pending review because the uploaded image may not be related to a phishing or scam message."
                )
                return redirect('message_list')
            elif updated_message.moderation_status == ModerationStatus.PENDING:
                messages.success(request, "Your updated message was submitted and is pending moderator review.")
                return redirect('message_list')
            else:
                messages.success(request, "Your message was updated successfully.")
                return redirect('message_detail', message_id=message.id)
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
def edit_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)

    if comment.user != request.user:
        return redirect('message_detail', message_id=comment.message.id)

    if request.method == 'POST':
        form = CommentForm(request.POST, instance=comment)
        if form.is_valid():
            updated_comment = form.save(commit=False)
            updated_comment.user = request.user
            updated_comment.message = comment.message

            moderation_result = getattr(form, '_moderation_result', None)
            if moderation_result:
                updated_comment.moderation_status = moderation_result.status
                updated_comment.moderation_reason = moderation_result.reason
                updated_comment.moderation_score = moderation_result.score
                updated_comment.requires_human_review = moderation_result.requires_human_review

            updated_comment.save()

            if updated_comment.moderation_status == ModerationStatus.PENDING:
                messages.success(request, "Your updated comment was submitted and is pending moderator review.")
            else:
                messages.success(request, "Your comment was updated successfully.")

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
                    profile.moderation_score = bio_result.score
                    profile.requires_human_review = bio_result.requires_human_review

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
def report_message(request, message_id):
    message = get_object_or_404(Message, id=message_id, is_removed=False)

    existing_report = MessageReport.objects.filter(message=message, reporter=request.user).first()
    if existing_report:
        messages.info(request, "You have already reported this message.")
        return redirect('message_detail', message_id=message.id)

    if request.method == 'POST':
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
def report_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id, is_removed=False)

    existing_report = CommentReport.objects.filter(comment=comment, reporter=request.user).first()
    if existing_report:
        messages.info(request, "You have already reported this comment.")
        return redirect('message_detail', message_id=comment.message.id)

    if request.method == 'POST':
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