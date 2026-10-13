"""门店员工账号与权限组。"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

FRONT_GROUP = "前台"
CARER_GROUP = "护理师"

FRONT_PERMS = (
    "view_owner",
    "add_owner",
    "change_owner",
    "view_pet",
    "add_pet",
    "change_pet",
    "view_room",
    "change_room",
    "view_order",
    "add_order",
    "change_order",
    "view_payment",
    "view_servicerecord",
    "add_servicerecord",
    "change_servicerecord",
    "view_review",
    "change_review",
)

CARER_PERMS = (
    "view_pet",
    "view_order",
    "view_room",
    "view_servicerecord",
    "add_servicerecord",
    "change_servicerecord",
)


def ensure_store_groups() -> tuple[Group, Group]:
    """确保「前台」「护理师」权限组存在并写入课题所需权限。"""
    front, _ = Group.objects.get_or_create(name=FRONT_GROUP)
    front.permissions.set(Permission.objects.filter(codename__in=FRONT_PERMS))
    carer, _ = Group.objects.get_or_create(name=CARER_GROUP)
    carer.permissions.set(Permission.objects.filter(codename__in=CARER_PERMS))
    return front, carer


def create_store_user(
    username: str,
    password: str,
    *,
    name: str = "",
    email: str = "",
    role: str = "front",
    superuser: bool = False,
):
    """
    创建门店账号。
    role: front（前台）| carer（护理师）| admin（超级用户，忽略 role 分组）
    """
    User = get_user_model()
    front, carer = ensure_store_groups()
    defaults = {
        "email": email,
        "first_name": name or username,
        "is_staff": True,
    }
    if superuser or role == "admin":
        user, created = User.objects.get_or_create(username=username, defaults={**defaults, "is_superuser": True})
        update_fields = []
        if created or not user.check_password(password):
            user.set_password(password)
            update_fields.append("password")
        if not user.is_staff:
            user.is_staff = True
            update_fields.append("is_staff")
        if not user.is_superuser:
            user.is_superuser = True
            update_fields.append("is_superuser")
        if created:
            user.save()
        elif update_fields:
            user.save(update_fields=update_fields)
        return user

    user, created = User.objects.get_or_create(username=username, defaults=defaults)
    if created:
        user.set_password(password)
        user.is_staff = True
        user.save()
    else:
        changed = []
        if not user.is_staff:
            user.is_staff = True
            changed.append("is_staff")
        if not user.check_password(password):
            user.set_password(password)
            changed.append("password")
        if changed:
            user.save(update_fields=changed)

    group = carer if role == "carer" else front
    user.groups.add(group)
    return user
