from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm

from .forms import LoginGuardMixin


class AdminLoginForm(LoginGuardMixin, AdminAuthenticationForm):
    pass


admin.site.login_form = AdminLoginForm
