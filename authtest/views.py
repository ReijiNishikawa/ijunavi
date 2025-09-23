from django.shortcuts import render

# Create your views here.

def home(request):
    return render(request, 'ijunavi/chat.html', {})

def top(request):
    return render(request, 'ijunavi/top.html', {})

def login(request):
    return render(request, 'login.html', {})