import uuid
from .models import Users
from django.urls import reverse
from django.core.mail import send_mail
from django.contrib.auth import authenticate, login as auth_login
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from .forms import SignInForm, LoginForm
from django.utils import timezone
from datetime import timedelta
from django.shortcuts import get_object_or_404

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
                if not user.is_verified:
                    error = "メール認証が完了していません。メールを確認してください。"
                else:
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
            email = signup_form.cleaned_data['email']

            existing_user = Users.objects.filter(email=email).first()

            if existing_user:
                if not existing_user.is_verified:
                    existing_user.verification_token = uuid.uuid4()
                    existing_user.token_created_at = timezone.now()
                    existing_user.save()

                    verification_url = request.build_absolute_uri(
                        reverse('verify_user', args=[existing_user.verification_token])
                    )

                    send_mail(
                        'いじゅナビ会員登録',
                        f'いじゅナビ 会員登録のご案内\n\n'
                        f'この度は、いじゅナビにご登録いただき誠にありがとうございます。\n'
                        f'以下のURLより、アカウント登録を完了してください。\n\n'
                        f'{verification_url}\n\n'
                        f'本URLは発行から10分間のみ有効です。\n'
                        f'お早めにアクセスいただき、登録手続きを完了してください。\n\n'
                        f'なお、このメールに心当たりがない場合は、\n'
                        f'お手数ですが本メールを破棄していただきますようお願いいたします。',
                        'ijunavi@gmail.com',
                        [user.email],
                    )
                    return render(request, 'accounts/registration_sent.html')
                
                signup_form.add_error('email', 'このメールアドレスは既に登録されています。')
                return render(request, 'accounts/signup.html', {'signin_form': signup_form})

            try:
                user = signup_form.save(commit=False)
                user.is_verified = False
                user.verification_token = uuid.uuid4()
                user.token_created_at = timezone.now()
                user.save()

                verification_url = request.build_absolute_uri(
                    reverse('verify_user', args=[user.verification_token])
                )

                send_mail(
                    'いじゅナビ会員登録',
                    f'いじゅナビ 会員登録のご案内\n\n'
                    f'この度は、いじゅナビにご登録いただき誠にありがとうございます。\n'
                    f'以下のURLより、アカウント登録を完了してください。\n\n'
                    f'{verification_url}\n\n'
                    f'本URLは発行から10分間のみ有効です。\n'
                    f'お早めにアクセスいただき、登録手続きを完了してください。\n\n'
                    f'なお、このメールに心当たりがない場合は、\n'
                    f'お手数ですが本メールを破棄していただきますようお願いいたします。',
                    'ijunavi@gmail.com',
                    [user.email],
                )
                return render(request, 'accounts/registration_sent.html')
            
            except ValidationError as e:
                signup_form.add_error('password1', e.messages)

    else:
        signup_form = SignInForm()

    return render(request, 'accounts/signup.html', {
        'signin_form': signup_form,
    })

def verify_user(request, token):
    user = get_object_or_404(Users, verification_token=token)

    if timezone.now() - user.token_created_at > timedelta(minutes=10):
        return render(request, 'accounts/token_expired.html')

    user.is_verified = True
    user.verification_token = None
    user.token_created_at = None
    user.save()
    return render(request, 'accounts/registration_complete.html')
