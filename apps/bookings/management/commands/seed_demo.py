from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.bookings.models import Order, Payment
from apps.care.models import Review, ServiceRecord
from apps.pets.models import Owner, Pet, PetSize, Species
from apps.rooms.models import Room
from apps.stores.models import Store
from apps.stores.staff import create_store_user, ensure_store_groups

STOCK = Path(settings.BASE_DIR) / "static" / "img" / "stock"
DEMO_PASSWORD = "pawstay123"
# 门店演示账号（官网登录选「门店」）
STORE_ADMIN = ("admin", "admin123", "门店管理员")
STORE_FRONT = ("13900000001", DEMO_PASSWORD, "前台小陈")
STORE_CARER = ("13900000002", DEMO_PASSWORD, "护理师小赵")

# 约 6 间：覆盖猫/狗 × 标准/豪华/套房(VIP)
ROOMS = [
    {
        "number": "A101",
        "name": "阳光标准间",
        "room_type": Room.RoomType.STANDARD,
        "pet_type": Room.PetType.DOG,
        "max_pet_size": PetSize.MEDIUM,
        "price": "88",
        "capacity": 2,
        "area": "6",
        "amenities": "恒温空调,24h监控,软垫睡床,每日两次遛弯",
        "photo": "room-dog-standard",
        "description": "朝南采光的标准独立间，配备加厚记忆棉睡垫。适合中小型犬，同一家庭可合住两只。",
    },
    {
        "number": "A201",
        "name": "大床豪华间",
        "room_type": Room.RoomType.DELUXE,
        "pet_type": Room.PetType.DOG,
        "max_pet_size": PetSize.LARGE,
        "price": "168",
        "capacity": 1,
        "area": "12",
        "amenities": "独立新风,24h监控,宠物沙发,独立活动区,每日视频",
        "photo": "room-dog-deluxe",
        "description": "单宠独享 12㎡，配宠物沙发与玩具角。一对一互动更多，适合中大型犬或不愿合笼的狗狗。",
    },
    {
        "number": "A301",
        "name": "阳光 VIP 套房",
        "room_type": Room.RoomType.VIP,
        "pet_type": Room.PetType.DOG,
        "max_pet_size": PetSize.LARGE,
        "price": "358",
        "capacity": 2,
        "area": "18",
        "amenities": "独立小院,落地窗,24h摄像头,每日视频,专属护理师",
        "photo": "room-dog-vip",
        "description": "带独立小院的 VIP 套房，阳光充足。可两只大型犬同住，含专属护理与实时监控。",
    },
    {
        "number": "B101",
        "name": "猫咪乐园间",
        "room_type": Room.RoomType.STANDARD,
        "pet_type": Room.PetType.CAT,
        "max_pet_size": PetSize.MEDIUM,
        "price": "68",
        "capacity": 3,
        "area": "8",
        "amenities": "猫爬架,恒温空调,24h监控,猫咪安静区",
        "photo": "room-cat-play",
        "description": "位于猫咪安静区，远离犬只叫声。多层猫爬架与逗猫玩具，每天两次互动陪玩。",
    },
    {
        "number": "B102",
        "name": "猫咪豪华间",
        "room_type": Room.RoomType.DELUXE,
        "pet_type": Room.PetType.CAT,
        "max_pet_size": PetSize.MEDIUM,
        "price": "98",
        "capacity": 2,
        "area": "9",
        "amenities": "双层猫别墅,恒温空调,24h监控,每日视频",
        "photo": "room-cat-deluxe",
        "description": "双层猫别墅结构，空间与隔音升级。适合两只性格合拍的猫咪同住。",
    },
    {
        "number": "B201",
        "name": "观景猫套房",
        "room_type": Room.RoomType.SUITE,
        "pet_type": Room.PetType.CAT,
        "max_pet_size": PetSize.LARGE,
        "price": "138",
        "capacity": 1,
        "area": "10",
        "amenities": "落地观景窗,独立新风,猫爬架,每日视频,24h监控",
        "photo": "room-cat-suite",
        "description": "实墙独立套房，窗台可晒太阳看风景。适合胆小、老年或易应激、需要独处的猫咪。",
    },
]


def _attach(instance, field: str, slot: str):
    path = STOCK / f"{slot}.jpg"
    if path.exists():
        with path.open("rb") as fh:
            getattr(instance, field).save(f"{slot}.jpg", File(fh), save=True)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    moment = datetime.combine(day, time(hour, minute), tzinfo=timezone.get_current_timezone())
    return min(moment, timezone.now())


def _backdate(order: Order, lead_days: int = 7):
    """业务方法按“当前时间”打时间戳；演示订单需要挪到与入住日期吻合的时间点。"""
    booked = _at(order.check_in - timedelta(days=lead_days), 20, 30)
    paid = booked + timedelta(minutes=4) if order.paid_at else None
    checked_in = None
    if order.checked_in_at:
        first_care = order.service_records.order_by("feeding_time").first()
        checked_in = _at(order.check_in, 10, 15)
        if first_care:
            checked_in = min(checked_in, first_care.feeding_time - timedelta(hours=1))
    checked_out = _at(order.check_out, 16, 40) if order.checked_out_at else None
    Order.objects.filter(pk=order.pk).update(
        order_no=f"O{timezone.localtime(booked):%Y%m%d}{order.pk:05d}",
        created_at=booked,
        paid_at=paid,
        checked_in_at=checked_in,
        checked_out_at=checked_out,
    )
    order.refresh_from_db()
    order.payments.update(created_at=paid or booked)
    Review.objects.filter(order=order).update(created_at=_at(order.check_out + timedelta(days=1), 21))


class Command(BaseCommand):
    help = (
        f"写入演示数据：门店 admin/admin123、前台 {STORE_FRONT[0]}/{DEMO_PASSWORD}；"
        f"顾客 13800000001/{DEMO_PASSWORD}（已有顾客业务数据则跳过订单注入）"
    )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        self._seed_store_staff()

        flagship = Store.objects.filter(code="flagship").first() or Store.default()
        Room.objects.filter(store__isnull=True).update(store=flagship)

        rooms = {}
        created_rooms = 0
        for spec in ROOMS:
            spec = dict(spec)
            slot = spec.pop("photo")
            defaults = {**spec, "price": Decimal(spec["price"]), "area": Decimal(spec["area"])}
            room, created = Room.objects.get_or_create(
                store=flagship, number=spec["number"], defaults=defaults
            )
            if created:
                created_rooms += 1
            _attach(room, "photo", slot)  # 演示房统一刷新占位图，避免多间共用同一张
            rooms[room.number] = room
        if created_rooms:
            self.stdout.write(f"已补充 {created_rooms} 间演示房间")
        self.stdout.write(f"已刷新 {len(rooms)} 间演示房间照片")

        # 本店仅接待猫狗：下架历史异宠样例房
        hidden = Room.objects.filter(pet_type__in=("rabbit", "bird", "other")).update(is_listed=False)
        if hidden:
            self.stdout.write(f"已下架 {hidden} 间非猫狗房间")

        if Owner.objects.filter(phone="13800000001").exists():
            self.stdout.write(self.style.WARNING("已存在演示顾客，跳过订单与评价演示数据（门店账号已确保可用）"))
            return

        today = timezone.localdate()
        vaccine = today + timedelta(days=300)

        def customer(name, phone, **extra):
            user = User.objects.create_user(username=phone, password=DEMO_PASSWORD, first_name=name)
            return Owner.objects.create(user=user, name=name, phone=phone, **extra)

        zhang = customer(
            "张伟",
            "13800000001",
            address="徐汇区幸福小区 1 栋",
            emergency_contact="张妈妈",
            emergency_phone="13900000001",
        )
        li = customer("李娜", "13800000002", address="静安区阳光花园 3 栋")
        wang = Owner.objects.create(name="王芳", phone="13800000003", address="长宁区")

        def pet(owner, slot, **fields):
            p = Pet.objects.create(
                owner=owner, vaccine_expiry=vaccine, deworm_expiry=today + timedelta(days=60), **fields
            )
            _attach(p, "photo", slot)
            return p

        wangcai = pet(
            zhang,
            "pet-golden",
            name="旺财",
            species=Species.DOG,
            breed="金毛",
            age=3,
            gender=Pet.Gender.MALE,
            weight=Decimal("22"),
            sterilized=True,
            temperament=Pet.Temperament.ACTIVE,
            diet_notes="早晚各一餐，每餐 200g 狗粮",
            allergies="对鸡肉过敏",
        )
        mimi = pet(
            li,
            "pet-british",
            name="咪咪",
            species=Species.CAT,
            breed="英国短毛猫",
            age=2,
            gender=Pet.Gender.FEMALE,
            weight=Decimal("4.5"),
            sterilized=True,
            temperament=Pet.Temperament.TIMID,
            diet_notes="自由采食，每天一个罐头",
        )
        doudou = pet(
            li,
            "pet-corgi",
            name="豆豆",
            species=Species.DOG,
            breed="柯基",
            age=1,
            gender=Pet.Gender.FEMALE,
            weight=Decimal("11"),
            temperament=Pet.Temperament.GENTLE,
        )
        kele = pet(
            wang,
            "pet-labrador",
            name="可乐",
            species=Species.DOG,
            breed="拉布拉多",
            age=5,
            gender=Pet.Gender.MALE,
            weight=Decimal("28"),
        )

        def history(p, room, start, nights, rating, content, reply=""):
            o = Order.objects.create(
                pet=p,
                room=room,
                check_in=today + timedelta(days=start),
                check_out=today + timedelta(days=start + nights),
                source=Order.Source.ONLINE,
            )
            o.pay(Payment.Method.ONLINE)
            o.start_boarding()
            ServiceRecord.objects.create(
                order=o,
                staff="赵护理",
                care_content="早餐按量喂食，饮水正常，精神很好",
                appetite="全部吃完",
                health_status="良好",
                feeding_time=_at(o.check_in + timedelta(days=1), 8, 30),
            )
            o.finish_boarding()
            Review.objects.create(order=o, rating=rating, content=content, reply=reply)
            _backdate(o)
            return o

        history(
            mimi,
            rooms["B201"],
            -40,
            5,
            5,
            "咪咪平时很胆小，在观景套房里居然会趴窗台晒太阳了，每天都有照片，太安心了！",
            "谢谢信任，咪咪是我们见过最乖的小公主～",
        )
        history(wangcai, rooms["A201"], -30, 4, 5, "房间很大很干净，旺财回家后状态特别好，护理记录写得非常细。")
        history(
            doudou, rooms["A101"], -20, 3, 4, "遛弯很准时，就是希望能多发几个视频。", "收到建议，豪华间已支持每日视频～"
        )

        boarding = Order.objects.create(
            pet=wangcai,
            room=rooms["A101"],
            check_in=today - timedelta(days=2),
            check_out=today + timedelta(days=3),
            source=Order.Source.ONLINE,
            note="旺财对鸡肉过敏，请不要喂鸡肉零食",
        )
        boarding.pay(Payment.Method.ONLINE)
        boarding.start_boarding()
        for day, hour, slot, content, appetite, health, note in [
            (0, 18, "care-golden-eat", "晚餐 200g 狗粮全部吃完，饮水正常", "全部吃完", "良好", ""),
            (1, 8, "", "早餐只吃了一半，精神尚可", "吃了一半", "良好", ""),
            (1, 17, "care-golden-walk", "傍晚在草坪遛弯 40 分钟，和小伙伴玩得很开心", "非喂食记录", "良好", ""),
            (
                1,
                20,
                "care-golden-bath",
                "洗澡、吹干、梳毛，检查耳朵和指甲",
                "非喂食记录",
                "一般",
                "轻微掉毛，换季正常现象，持续观察",
            ),
        ]:
            record = ServiceRecord(
                order=boarding,
                staff="王护理",
                care_content=content,
                appetite=appetite,
                health_status=health,
                health_note=note,
                feeding_time=_at(boarding.check_in + timedelta(days=day), hour),
            )
            record.save()
            if slot:
                _attach(record, "photo", slot)
        _backdate(boarding)

        departing = Order.objects.create(
            pet=mimi,
            room=rooms["B201"],
            check_in=today - timedelta(days=3),
            check_out=today,
            source=Order.Source.ONLINE,
        )
        departing.pay(Payment.Method.ONLINE)
        departing.start_boarding()
        ServiceRecord.objects.create(
            order=departing,
            staff="赵护理",
            care_content="猫粮与冻干按量喂食，猫砂已清理，窗台晒太阳一下午",
            appetite="全部吃完",
            health_status="良好",
            feeding_time=_at(today - timedelta(days=1), 18),
        )
        _backdate(departing)
        arriving = Order.objects.create(
            pet=kele,
            room=rooms["A201"],
            check_in=today,
            check_out=today + timedelta(days=4),
            source=Order.Source.ONLINE,
            note="下午三点左右到店，自带狗粮",
        )
        arriving.pay(Payment.Method.ONLINE)
        _backdate(arriving, lead_days=3)

        upcoming = Order.objects.create(
            pet=doudou,
            room=rooms["A101"],
            check_in=today + timedelta(days=5),
            check_out=today + timedelta(days=12),
            source=Order.Source.ONLINE,
        )
        upcoming.pay(Payment.Method.ONLINE)
        _backdate(upcoming)
        phone_booking = Order.objects.create(
            pet=mimi,
            room=rooms["B101"],
            check_in=today + timedelta(days=20),
            check_out=today + timedelta(days=23),
            source=Order.Source.FRONT_DESK,
            note="电话预约，到店付款",
        )
        _backdate(phone_booking, lead_days=21)
        months_ago = timezone.now() - timedelta(days=60)
        Owner.objects.update(created_at=months_ago)
        Pet.objects.update(created_at=months_ago)

        self.stdout.write(
            self.style.SUCCESS(
                "演示数据写入完成；"
                f"门店 admin/admin123、前台 {STORE_FRONT[0]}/{DEMO_PASSWORD}、护理 {STORE_CARER[0]}/{DEMO_PASSWORD}；"
                f"顾客 13800000001/{DEMO_PASSWORD}"
            )
        )

    def _seed_store_staff(self):
        """注入门店超级管理员、前台、护理师账号。"""
        ensure_store_groups()
        admin_user = create_store_user(
            STORE_ADMIN[0], STORE_ADMIN[1], name=STORE_ADMIN[2], email="admin@example.com", role="admin"
        )
        front_user = create_store_user(STORE_FRONT[0], STORE_FRONT[1], name=STORE_FRONT[2], role="front")
        carer_user = create_store_user(STORE_CARER[0], STORE_CARER[1], name=STORE_CARER[2], role="carer")
        self.stdout.write(
            f"门店账号就绪：管理员 {admin_user.username}、前台 {front_user.username}、护理师 {carer_user.username}"
        )
