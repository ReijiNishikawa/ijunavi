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
    
    def save(self):
        user = super().save(commit=False)
        validate_password(self.cleaned_data.get('password'), user)
        user.set_password(self.cleaned_data.get('password'))
        user.save()
        return user