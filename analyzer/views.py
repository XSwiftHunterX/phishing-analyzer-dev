from django.shortcuts import render
from .models import Message

# Create your views here.

def message_list(request):
    messages = Message.objects.all().order_by('-submission_date')
    return render(request, 'analyzer/message_list.html', {'messages': messages})