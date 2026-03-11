from django.contrib import admin
from .models import Message, Comment

# Register your models here.
admin.site.register(Message)
admin.site.register(Comment)