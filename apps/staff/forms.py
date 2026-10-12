from django import forms

from apps.care.models import ServiceRecord

QUICK_PHRASES = {
    "喂食": ["早餐", "晚餐", "加餐零食", "饮水正常"],
    "日常": ["遛弯 30 分钟", "陪玩互动", "梳毛", "清理便盆/窝垫"],
    "护理": ["洗澡吹干", "按时喂药", "体温正常", "精神状态良好"],
}


class CareRecordForm(forms.ModelForm):
    class Meta:
        model = ServiceRecord
        fields = ["care_content", "appetite", "health_status", "health_note", "photo"]
        widgets = {
            "care_content": forms.Textarea(
                attrs={"rows": 3, "class": "form-control", "placeholder": "如：晚餐 200g 全部吃完，饭后散步 20 分钟"}
            ),
            "appetite": forms.RadioSelect(attrs={"class": "btn-check"}),
            "health_status": forms.RadioSelect(attrs={"class": "btn-check"}),
            "health_note": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "健康状态为一般或异常时请说明，会同步提醒主人"}
            ),
            "photo": forms.FileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                    "capture": "environment",
                    "data-preview": "#carePhotoPreview",
                }
            ),
        }

    def __init__(self, *args, order, staff_name: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.order = order
        self.instance.staff = staff_name
        self.fields["appetite"].label = "进食情况"

    def clean(self):
        data = super().clean()
        if data.get("health_status") != ServiceRecord.Health.GOOD and not data.get("health_note"):
            self.add_error("health_note", "健康状态为一般或异常时，请填写具体情况")
        return data
