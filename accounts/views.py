from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from . import forms


def signin(request):
    signin_form = forms.SignInForm(request.POST or None)
    if signin_form.is_valid():
        try:
            signin_form.save()
            return redirect('accounts:home')
        except ValidationError as e:
            signin_form.add_error('password', e)
    return render(request,'accounts/signin.html', context={
        'signin_form': signin_form,
    })