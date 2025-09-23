from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from . import forms

# Create your views here.

def home(request):
    return render(request, 'ijunavi/chat.html', {})

def top(request):
    return render(request, 'ijunavi/top.html', {})

def signup_view(request):
    return render(request, 'accounts/signup.html', {})

def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        user = authenticate(request, email=email, password=password)

        if user is not None:
            auth_login(request, user)
            return redirect("home")
        else:
            return render(request, "login.html", {"error": "メールまたはパスワードが違います"})
        
    return render(request, 'accounts/login.html', {})

def signin(request):
    signin_form = forms.SignInForm(request.POST or None)
    if signin_form.is_valid():
        try:
            signin_form.save()
            return redirect('home')
        except ValidationError as e:
            signin_form.add_error('password', e)
    return render(request,'ijunavi/signup.html', context={
        'signin_form': signin_form,
    })