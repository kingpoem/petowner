from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm

from .forms import LoginGuardMixin
from .models import TOTPDevice


class AdminLoginForm(LoginGuardMixin, AdminAuthenticationForm):
    pass


admin.site.login_form = AdminLoginForm


@admin.register(TOTPDevice)
class TOTPDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "confirmed_at", "last_used_at")
    search_fields = ("user__username", "user__first_name")
    readonly_fields = ("user", "confirmed_at", "last_used_at")
    exclude = ("secret", "last_step")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_model_perms(self, request):
        # 仅超级管理员可见：员工更换手机时由其删除绑定记录，员工下次登录重新绑定
        return super().get_model_perms(request) if request.user.is_superuser else {}
