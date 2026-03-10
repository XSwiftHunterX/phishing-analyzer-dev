from django.urls import path
from . import views

urlpatterns = [
    path('', views.message_list, name='message_list'),
    path('submit/', views.submit_message, name='submit_message'),
]