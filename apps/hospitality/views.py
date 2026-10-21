from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.web.views import owner_required

from .forms import MedicationForm
from .models import Medication


def service_menu(request):
    """兼容旧链接：增值服务已并入护理服务页。"""
    return redirect("web:care")


@owner_required
def pet_health(request, pk):
    pet = get_object_or_404(request.owner.pets, pk=pk)
    med_form = MedicationForm(request.POST or None)
    if request.method == "POST" and med_form.is_valid():
        med = med_form.save(commit=False)
        med.pet = pet
        med.save()
        messages.success(request, f"已加入用药计划：{med.drug}")
        return redirect("hospitality:pet_health", pk=pet.pk)
    return render(
        request,
        "hospitality/health.html",
        {
            "pet": pet,
            "med_form": med_form,
            "meds": pet.medications.all(),
        },
    )


@owner_required
@require_POST
def stop_medication(request, pk):
    med = get_object_or_404(Medication, pk=pk, pet__owner=request.owner)
    med.is_active = False
    med.save(update_fields=["is_active"])
    messages.success(request, f"已停用 {med.drug}")
    return redirect("hospitality:pet_health", pk=med.pet_id)
