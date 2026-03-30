from django.urls import path
from . import views

urlpatterns = [
    path('', views.message_list, name='message_list'),
    path('submit/', views.submit_message, name='submit_message'),
    path('submit/processing/<int:message_id>/', views.processing_message, name='processing_message'),
    path('submit/finalize/<int:message_id>/', views.finalize_message_submission, name='finalize_message_submission'),

    path('edit/<int:message_id>/', views.edit_message, name='edit_message'),
    path('delete/<int:message_id>/', views.delete_message, name='delete_message'),
    path('message/<int:message_id>/', views.message_detail, name='message_detail'),

    path('comment/edit/<int:comment_id>/', views.edit_comment, name='edit_comment'),
    path('comment/delete/<int:comment_id>/', views.delete_comment, name='delete_comment'),

    path('message/<int:message_id>/like/', views.toggle_message_like, name='toggle_message_like'),
    path('comment/<int:comment_id>/like/', views.toggle_comment_like, name='toggle_comment_like'),

    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('user/<str:username>/', views.user_messages, name='user_messages'),
    path('profile/delete/', views.delete_account, name='delete_account'),

    path('message/<int:message_id>/report/', views.report_message, name='report_message'),
    path('comment/<int:comment_id>/report/', views.report_comment, name='report_comment'),
    path('profile/<str:username>/report/', views.report_profile, name='report_profile'),
]