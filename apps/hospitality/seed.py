"""可重复执行的商业目录与演示档案。"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.pets.models import Pet

from .models import (
    AddonService,
    Billing,
    HolidayRate,
    Medication,
    OrderAddon,
    StaffMember,
    StoreNotice,
    Supply,
)


def seed_catalog():
    services = [
        ("pickup", "上门接送", "专车接送，减少旅途惊吓", "bi-car-front", "80", Billing.ONCE, "any", 1),
        (
            "walk",
            "加长遛弯",
            "在每日两次之外，再加一次 40 分钟散步",
            "bi-signpost-split",
            "30",
            Billing.NIGHT,
            "dog",
            2,
        ),
        ("video", "视频探视", "护理师每天发一段短视频", "bi-camera-video", "15", Billing.NIGHT, "any", 3),
        ("meds", "喂药照护", "按用药计划喂药并记录反应", "bi-capsule", "20", Billing.NIGHT, "any", 4),
        ("bath", "离店洗护", "离店当天洗澡、吹干、梳毛", "bi-droplet", "128", Billing.ONCE, "any", 5),
        ("spa", "精致 SPA", "药浴或护毛，适合皮肤敏感的宠物", "bi-stars", "168", Billing.ONCE, "any", 6),
        ("party", "生日布置", "小蛋糕、拍照和房间布置", "bi-balloon-heart", "199", Billing.ONCE, "any", 7),
    ]
    for code, name, summary, icon, price, billing, species, sort in services:
        AddonService.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "summary": summary,
                "description": summary,
                "icon": icon,
                "price": Decimal(price),
                "billing": billing,
                "species": species,
                "is_active": True,
                "sort": sort,
            },
        )
    for name, role, skills in (
        ("赵护理", StaffMember.Role.CARER, "犬只行为、喂药"),
        ("陈前台", StaffMember.Role.FRONT, "预约、收银、接送"),
        ("周店长", StaffMember.Role.MANAGER, "排班、客诉、定价"),
    ):
        StaffMember.objects.update_or_create(name=name, defaults={"role": role, "skills": skills, "is_active": True})
    for name, unit, stock, reorder in (
        ("成犬粮", "kg", "40", "8"),
        ("猫砂", "袋", "25", "6"),
        ("低敏洗护液", "瓶", "12", "3"),
    ):
        Supply.objects.update_or_create(
            name=name,
            defaults={"unit": unit, "stock": Decimal(stock), "reorder_level": Decimal(reorder)},
        )
    today = timezone.localdate()
    HolidayRate.objects.update_or_create(
        day=today + timedelta(days=18),
        defaults={"label": "店庆", "multiplier": Decimal("1.20"), "is_active": True},
    )
    StoreNotice.objects.update_or_create(
        title="入住请携带日常口粮与熟悉用品",
        defaults={
            "body": "自带口粮可减少换粮应激；小毯子或玩具有助于安抚。可在「健康护照」里登记寄养期间的用药计划。",
            "is_published": True,
            "pinned": True,
        },
    )


def seed_story():
    pet = Pet.objects.filter(name="旺财").first()
    if pet is None:
        return
    if not pet.medications.filter(drug="抗过敏片").exists():
        Medication.objects.create(
            pet=pet,
            drug="抗过敏片",
            dosage="半片",
            frequency="发现抓挠时喂一次，每日不超过两次",
            note="对鸡肉过敏，不要用含鸡肉的奖励",
        )


def attach_demo_addon(order, code="video"):
    service = AddonService.objects.filter(code=code, is_active=True).first()
    if service is None or order.addons.exists():
        return
    units = order.days if service.billing == Billing.NIGHT else 1
    total = (service.price * units).quantize(Decimal("0.01"))
    OrderAddon.objects.create(
        order=order,
        service=service,
        unit_price=service.price,
        nights=order.days,
        line_total=total,
    )
    order.addon_amount = total
    order.save()
