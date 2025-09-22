from django.shortcuts import render, redirect
import random
from django.http import HttpResponse
from django.http import Http404
from django.utils import timezone

# Create your views here.
def top(request):
    return render(request, 'ijunavi/top.html')

def login_view(request):
    return render(request, 'ijunavi/login.html')

def signup_view(request):
    return render(request, 'ijunavi/signup.html')