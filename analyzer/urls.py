from django.urls import path
from . import views

urlpatterns = [
    path('', views.message_list, name='message_list'),
    path('submit/', views.submit_message, name='submit_message'),
    path('register/', views.register, name='register'),
    path('edit/<int:message_id>/', views.edit_message, name='edit_message'),
    path('delete/<int:message_id>/', views.delete_message, name='delete_message'),
    path('message/<int:message_id>/', views.message_detail, name='message_detail'),
    path('comment/edit/<int:comment_id>/', views.edit_comment, name='edit_comment'),
    path('comment/delete/<int:comment_id>/', views.delete_comment, name='delete_comment'),
    path('message/<int:message_id>/second/', views.toggle_second, name='toggle_second'),
    path('comment/<int:comment_id>/like/', views.toggle_comment_like, name='toggle_comment_like'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
]