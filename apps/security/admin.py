from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import logout

from .forms import LoginGuardMixin


class AdminLoginForm(LoginGuardMixin, AdminAuthenticationForm):
    pass


admin.site.login_form = AdminLoginForm

_original_admin_login = admin.site.login


def _admin_login(request, extra_context=None):
    """顾客等非员工账号访问后台时先退出，要求用员工账号重新登录。"""
    user = request.user
    if user.is_authenticated and not (user.is_active and user.is_staff):
        logout(request)
    return _original_admin_login(request, extra_context)


admin.site.login = _admin_login
