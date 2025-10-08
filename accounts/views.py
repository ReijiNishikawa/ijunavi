from django.contrib.auth import authenticate, login as auth_login
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from .forms import SignInForm, LoginForm

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
                return redirect("chat")
            else:
                error = "メールまたはパスワードが違います。"
        
    return render(request, "registration/login.html", {
        "form": form,
        "error": error,
    })

def signup_view(request):
    if request.method == 'POST':
        signup_form = SignInForm(request.POST)
        if signup_form.is_valid():
            signup_form.save()
            return redirect('home')
    else:
        signup_form = SignInForm()

    return render(request, 'accounts/signup.html', {
        'signin_form': signup_form,
    })