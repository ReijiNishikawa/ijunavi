from django.urls import path, include
from . import views
from django.contrib.auth.views import LoginView, LogoutView
from .forms import SignInForm

urlpatterns = [
    path('', views.home, name='home'),
    path('top/', views.top, name='top'),
    path('accounts/login/', views.login_view, name='login'),
    path('accounts/logout/', LogoutView.as_view(), name='logout'),
    path('signup/', views.signup_view, name='signup'),  
]