"""认证后台：不维护权限组与用户列表；顾客账号在「主人信息」开通。"""

from django.contrib import admin
from django.contrib.auth.models import Group, User


def patch_auth_admin() -> None:
    if admin.site.is_registered(Group):
        admin.site.unregister(Group)
    if admin.site.is_registered(User):
        admin.site.unregister(User)
