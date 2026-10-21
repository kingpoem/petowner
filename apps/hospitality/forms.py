from django import forms

from .models import Medication


class MedicationForm(forms.ModelForm):
    class Meta:
        model = Medication
        fields = ["drug", "dosage", "frequency", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
