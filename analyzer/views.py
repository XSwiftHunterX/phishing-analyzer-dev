from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Message
from .forms import MessageForm, RegisterForm

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
        messages = messages.filter(message_content__icontains=query)

    if classification:
        messages = messages.filter(classification=classification)

    if suspected_risk:
        messages = messages.filter(suspected_risk=suspected_risk)

    if message_type:
        messages = messages.filter(message_type=message_type)

    context = {
        'messages': messages,
        'query': query or '',
        'selected_classification': classification or '',
        'selected_suspected_risk': suspected_risk or '',
        'selected_message_type': message_type or '',
    }

    return render(request, 'analyzer/message_list.html', context)

def message_detail(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    return render(request, 'analyzer/message_detail.html', {'message': message})

@login_required
def submit_message(request):
    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.user = request.user
            message.save()
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
        return redirect('message_list')

    return render(request, 'analyzer/delete_message.html', {'message': message})