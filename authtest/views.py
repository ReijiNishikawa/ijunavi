from django.shortcuts import render
from django.contrib.auth import authenticate, login

# Create your views here.

def home(request):
    return render(request, 'ijunavi/chat.html', {})

def top(request):
    return render(request, 'ijunavi/top.html', {})

def login(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            return redirect("home")
        else:
            return render(request, "login.html", {"erroe": "メールまたはパスワードが違います"})
        
    return render(request, 'login.html', {})