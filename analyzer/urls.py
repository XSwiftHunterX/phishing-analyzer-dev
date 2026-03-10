from django.urls import path
from . import views

urlpatterns = [
    path('', views.message_list, name='message_list'),
    path('submit/', views.submit_message, name='submit_message'),
    path('register/', views.register, name='register'),
    path('edit/<int:message_id>/', views.edit_message, name='edit_message'),
    path('delete/<int:message_id>/', views.delete_message, name='delete_message'),
]