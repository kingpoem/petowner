from django.conf import settings
from django.db import models


class Store(models.Model):
    code = models.SlugField("门店编码", max_length=20, unique=True)
    name = models.CharField("门店名称", max_length=80)
    phone = models.CharField("电话", max_length=30, blank=True)
    address = models.CharField("地址", max_length=200, blank=True)
    hours = models.CharField("营业时间", max_length=80, blank=True)
    is_active = models.BooleanField("营业中", default=True)
    is_default = models.BooleanField("默认门店", default=False)
    sort = models.PositiveSmallIntegerField("排序", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "门店"
        verbose_name_plural = verbose_name
        ordering = ["sort", "pk"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Store.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)

    @classmethod
    def default(cls) -> "Store":
        store = cls.objects.filter(is_default=True, is_active=True).first()
        if store:
            return store
        store = cls.objects.filter(is_active=True).first()
        if store:
            return store
        return cls.objects.create(
            code="flagship",
            name=settings.SITE_NAME.split()[0] + "旗舰店" if settings.SITE_NAME else "旗舰店",
            phone=settings.SITE_PHONE,
            address=settings.SITE_ADDRESS,
            hours=settings.SITE_HOURS,
            is_default=True,
        )


class StaffStore(models.Model):
    """员工可管理的门店；未配置时视为可管理全部门店。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="员工", on_delete=models.CASCADE, related_name="store_memberships"
    )
    store = models.ForeignKey(Store, verbose_name="门店", on_delete=models.CASCADE, related_name="staff_members")

    class Meta:
        verbose_name = "员工门店权限"
        verbose_name_plural = verbose_name
        unique_together = ("user", "store")

    def __str__(self):
        return f"{self.user} @ {self.store}"
