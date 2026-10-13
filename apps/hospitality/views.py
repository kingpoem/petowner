from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.web.views import owner_required

from .forms import MedicationForm, VaccineForm, WaitlistForm
from .models import AddonService, Coupon, Medication, StoreNotice, WaitlistEntry, ensure_member


def service_menu(request):
    services = AddonService.objects.filter(is_active=True)
    coupons = Coupon.objects.filter(is_active=True)[:6]
    return render(request, "hospitality/services.html", {"services": services, "coupons": coupons})


@owner_required
def membership(request):
    account = ensure_member(request.owner)
    coupons = Coupon.objects.filter(is_active=True)
    entries = account.entries.select_related("order")[:12]
    return render(
        request,
        "hospitality/membership.html",
        {"account": account, "coupons": coupons, "entries": entries},
    )


@owner_required
def waitlist(request):
    form = WaitlistForm(request.POST or None, owner=request.owner)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.owner = request.owner
        entry.save()
        messages.success(request, "已加入候补，有空房时前台会按提交顺序联系你")
        return redirect("hospitality:waitlist")
    entries = WaitlistEntry.objects.filter(owner=request.owner).select_related("pet")
    return render(request, "hospitality/waitlist.html", {"form": form, "entries": entries})


@owner_required
def pet_health(request, pk):
    pet = get_object_or_404(request.owner.pets, pk=pk)
    vaccine_form = VaccineForm(request.POST or None if request.POST.get("kind") == "vaccine" else None)
    med_form = MedicationForm(request.POST or None if request.POST.get("kind") == "med" else None)
    if request.method == "POST" and request.POST.get("kind") == "vaccine" and vaccine_form.is_valid():
        record = vaccine_form.save(commit=False)
        record.pet = pet
        record.save()
        messages.success(request, f"已登记 {record.name}，档案有效期已同步")
        return redirect("hospitality:pet_health", pk=pet.pk)
    if request.method == "POST" and request.POST.get("kind") == "med" and med_form.is_valid():
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
            "vaccine_form": vaccine_form,
            "med_form": med_form,
            "vaccines": pet.vaccines.all(),
            "meds": pet.medications.all(),
            "notices": StoreNotice.published().filter(title__icontains="疫苗")[:1],
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
