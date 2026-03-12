from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Message, Comment
from .forms import MessageForm, RegisterForm, CommentForm, ProfileForm
from django.db.models import Q
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.contrib.auth import logout
from django.contrib import messages

# Create your views here.
def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("/accounts/login/")
    else:
        form = RegisterForm()

    return render(request, "analyzer/register.html", {"form": form})

def message_list(request):
    messages = Message.objects.all().order_by('-submission_date')

    query = request.GET.get('q')
    classification = request.GET.get('classification')
    suspected_risk = request.GET.get('suspected_risk')
    message_type = request.GET.get('message_type')

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

    paginator = Paginator(messages, 10)
    page_number = request.GET.get('page')
    message_page = paginator.get_page(page_number)

    context = {
        'message_page': message_page,
        'query': query or '',
        'selected_classification': classification or '',
        'selected_suspected_risk': suspected_risk or '',
        'selected_message_type': message_type or '',
    }

    return render(request, 'analyzer/message_list.html', context)

def message_detail(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    comments = message.comments.all().order_by('-created_at')

    has_liked_message = False
    if request.user.is_authenticated:
        has_liked_message = request.user in message.likes.all()

    for comment in comments:
        comment.has_liked = request.user.is_authenticated and request.user in comment.likes.all()

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('/accounts/login/')
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.message = message
            comment.user = request.user
            comment.save()
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
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.user = request.user
            message.save()
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
        form = MessageForm(request.POST, instance=message)
        if form.is_valid():
            updated_message = form.save(commit=False)
            updated_message.user = request.user
            updated_message.save()
            messages.success(request, "Your message was updated successfully.")
            return redirect('message_list')
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
            updated_comment.save()
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

    message_count = Message.objects.filter(user=profile_user).count()
    comment_count = Comment.objects.filter(user=profile_user).count()

    message_likes_received = 0
    user_messages = Message.objects.filter(user=profile_user)
    for message in user_messages:
        message_likes_received += message.likes.count()

    comment_likes_received = 0
    user_comments = Comment.objects.filter(user=profile_user)
    for comment in user_comments:
        comment_likes_received += comment.likes.count()

    context = {
        'profile_user': profile_user,
        'message_count': message_count,
        'comment_count': comment_count,
        'message_likes_received': message_likes_received,
        'comment_likes_received': comment_likes_received,
    }

    return render(request, 'analyzer/profile.html', context)

@login_required
def edit_profile(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile was updated successfully.")
            return redirect('profile')
    else:
        form = ProfileForm(instance=request.user)

    return render(request, 'analyzer/edit_profile.html', {'form': form})

def user_messages(request, username):
    user = get_object_or_404(User, username=username)

    user_posts = Message.objects.filter(user=user).order_by('-submission_date')

    context = {
        'profile_user': user,
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