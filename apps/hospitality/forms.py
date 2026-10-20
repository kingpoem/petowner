from django import forms
from django.core.exceptions import ValidationError

from apps.rooms.models import Room

from .models import Medication, VaccineRecord, WaitlistEntry


class DateInput(forms.DateInput):
    input_type = "date"


class WaitlistForm(forms.ModelForm):
    class Meta:
        model = WaitlistEntry
        fields = ["pet", "room_type", "check_in", "check_out", "note"]
        widgets = {"check_in": DateInput, "check_out": DateInput, "note": forms.TextInput}
        labels = {"note": "其他需求（选填）", "room_type": "期望房型"}

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pet"].queryset = owner.pets.all()
        self.fields["pet"].empty_label = "请选择宠物"
        self.fields["room_type"].widget = forms.Select(choices=[("", "不限房型"), *Room.RoomType.choices])
        self.fields["room_type"].required = False
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput | forms.Select):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")

    def clean(self):
        data = super().clean()
        start, end = data.get("check_in"), data.get("check_out")
        if start and end and end <= start:
            raise ValidationError("离店日期必须晚于入住日期")
        return data


class VaccineForm(forms.ModelForm):
    class Meta:
        model = VaccineRecord
        fields = ["name", "injected_on", "expires_on", "clinic", "batch", "note"]
        widgets = {"injected_on": DateInput, "expires_on": DateInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        data = super().clean()
        start, end = data.get("injected_on"), data.get("expires_on")
        if start and end and end < start:
            self.add_error("expires_on", "有效期不能早于接种日期")
        return data


class MedicationForm(forms.ModelForm):
    class Meta:
        model = Medication
        fields = ["drug", "dosage", "frequency", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
