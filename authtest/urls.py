from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('', views.top, name='top'),
    path('login/', views.login, name='login'),
]