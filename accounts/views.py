from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from .forms import SignInForm
from . import forms

# Create your views here.

def home(request):
    return render(request, 'ijunavi/chat.html', {})

def top(request):
    return render(request, 'ijunavi/top.html', {})

def login_view(request):
    form = LoginForm(request.POST or None)
    error = None

    if request.method == "POST":
        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]
            
            user = authenticate(request, email=email, password=password)

        if user is not None:
            auth_login(request, user)
            return redirect("home")
        else:
            return render(request, "login.html", {"error": "メールまたはパスワードが違います"})
        
    return render(request, 'registration/login.html', {})

def signup_view(request):
    if request.method == 'POST':
        signin_form = SignInForm(request.POST)
        if signin_form.is_valid():
            signin_form.save()
            return redirect('home')
    else:
        signin_form = SignInForm()

    return render(request, 'accounts/signup.html', {
        'signin_form': signin_form,
    })