from django.urls import path, include
from . import views
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth import views as auth_views
from .forms import SignInForm

urlpatterns = [
    path('top/', views.top, name='top'),
    path('accounts/login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),  
    path('verify/<uuid:token>/', views.verify_user, name='verify_user'),
    path("password_reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("password_reset_done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]