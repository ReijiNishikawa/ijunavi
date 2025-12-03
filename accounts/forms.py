from django import forms
from django.contrib.auth.password_validation import validate_password
from .models import Users

class SignInForm(forms.ModelForm):
    email = forms.EmailField(label='メールアドレス')
    password = forms.CharField(label='パスワード', widget=forms.PasswordInput)
    confirm_password = forms.CharField(label='パスワード再入力', widget=forms.PasswordInput)

    class Meta:
        model = Users
        fields = ('email', 'password')

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password != confirm_password:
            raise forms.ValidationError('パスワードが一致しません。')
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        validate_password(self.cleaned_data.get('password'), user)
        user.set_password(self.cleaned_data.get('password'))
        user.save()

        if commit:
            user.save()

        return user
    
class LoginForm(forms.Form):
    email = forms.EmailField(label="メールアドレス")
    password = forms.CharField(label="パスワード", widget=forms.PasswordInput)

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Users
        fields = ('username', 'email', 'icon')
        labels = {
            'username': 'ユーザー名',
            'email': 'メールアドレス',
            'icon': 'プロフィール画像',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['icon'].required = False

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            return email
        qs = Users.objects.exclude(pk=self.instance.pk).filter(email=email)
        if qs.exists():
            raise forms.ValidationError('このメールアドレスは既に使用されています。')
        return email
