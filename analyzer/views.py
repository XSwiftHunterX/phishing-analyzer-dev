from django.shortcuts import render, redirect
from .models import Message
from .forms import MessageForm

# Create your views here.

def message_list(request):
    messages = Message.objects.all().order_by('-submission_date')
    return render(request, 'analyzer/message_list.html', {'messages': messages})

def submit_message(request):
    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('message_list')
    else:
        form = MessageForm()

    return render(request, 'analyzer/submit_message.html', {'form': form})