from django.shortcuts import render, redirect
from .models import Message
from .forms import MessageForm

# Create your views here.

def message_list(request):
    messages = Message.objects.all().order_by('-submission_date')

    query = request.GET.get('q')
    classification = request.GET.get('classification')
    risk_level = request.GET.get('risk_level')
    message_type = request.GET.get('message_type')

    if query:
        messages = messages.filter(message_content__icontains=query)

    if classification:
        messages = messages.filter(classification=classification)

    if risk_level:
        messages = messages.filter(risk_level=risk_level)

    if message_type:
        messages = messages.filter(message_type=message_type)

    context = {
        'messages': messages,
        'query': query or '',
        'selected_classification': classification or '',
        'selected_risk_level': risk_level or '',
        'selected_message_type': message_type or '',
    }

    return render(request, 'analyzer/message_list.html', context)

def submit_message(request):
    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('message_list')
    else:
        form = MessageForm()

    return render(request, 'analyzer/submit_message.html', {'form': form})