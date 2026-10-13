"""测试用数据工厂。"""

from datetime import timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.bookings.models import Order
from apps.pets.models import Owner, Pet, Species
from apps.rooms.models import Room
from apps.stores.staff import create_store_user, ensure_store_groups

PASSWORD = "Test-pass-123"
STORE_PASSWORD = PASSWORD
_seq = count(1)


def today():
    return timezone.localdate()


def days(n: int):
    return today() + timedelta(days=n)


def make_owner(with_account: bool = True, **fields) -> Owner:
    n = next(_seq)
    phone = fields.pop("phone", f"139{n:08d}")
    user = None
    if with_account:
        user = get_user_model().objects.create_user(username=phone, password=PASSWORD, first_name=f"主人{n}")
    return Owner.objects.create(user=user, name=fields.pop("name", f"主人{n}"), phone=phone, **fields)


def make_pet(owner: Owner | None = None, **fields) -> Pet:
    defaults = {
        "name": f"宠物{next(_seq)}",
        "species": Species.DOG,
        "breed": "柯基",
        "weight": Decimal("8"),
        "vaccine_expiry": days(365),
    }
    return Pet.objects.create(owner=owner or make_owner(), **{**defaults, **fields})


def make_store(**fields):
    from apps.stores.models import Store

    n = next(_seq)
    defaults = {
        "code": f"s{n}",
        "name": f"测试门店{n}",
        "is_active": True,
        "is_default": False,
    }
    return Store.objects.create(**{**defaults, **fields})


def make_store_user(role: str = "front", **fields):
    """
    注入门店员工账号。
    role: front | carer | admin（超级用户）
    可用字段：username、password、name、email
    """
    n = next(_seq)
    username = fields.pop("username", f"store{n:04d}")
    password = fields.pop("password", STORE_PASSWORD)
    name = fields.pop("name", f"店员{n}")
    email = fields.pop("email", "")
    ensure_store_groups()
    return create_store_user(
        username,
        password,
        name=name,
        email=email,
        role=role,
        superuser=role == "admin",
    )


def make_room(**fields) -> Room:
    from apps.stores.models import Store

    defaults = {
        "number": f"R{next(_seq):03d}",
        "name": "测试房",
        "pet_type": Room.PetType.ANY,
        "price": Decimal("100"),
        "capacity": 1,
    }
    if "store" not in fields:
        store = Store.objects.filter(is_default=True).first()
        fields["store"] = store or make_store(is_default=True)
    return Room.objects.create(**{**defaults, **fields})


def make_order(pet: Pet | None = None, room: Room | None = None, start: int = 1, nights: int = 2, **fields) -> Order:
    order = Order(
        pet=pet or make_pet(),
        room=room or make_room(),
        check_in=days(start),
        check_out=days(start + nights),
        **fields,
    )
    order.full_clean()
    order.save()
    return order
