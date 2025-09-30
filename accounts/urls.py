from django.urls import path, include
from . import views
from django.contrib.auth.views import LoginView
from .forms import SignInForm

urlpatterns = [
    path('', views.home, name='home'),
    path('top/', views.top, name='top'),
    path('login/', views.login_view, name='login'),
    path('logout/', include('django.contrib.auth.urls')),  
    path('signup/', views.signup_view, name='signup'),  
]