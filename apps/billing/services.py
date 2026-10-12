"""电子收据开具与 PDF 生成。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone
from fpdf import FPDF

from apps.bookings.models import Order

from .models import Invoice


def create_invoice_request(order: Order, *, title: str, tax_no: str = "", email: str = "", kind: str = "") -> Invoice:
    if order.payment_status not in (Order.PaymentStatus.PAID, Order.PaymentStatus.PARTIAL, Order.PaymentStatus.REFUNDED):
        if order.net_paid <= 0:
            raise ValidationError("订单尚未支付，无法开具收据")
    if Invoice.objects.filter(order=order).exists():
        raise ValidationError("该订单已提交过开票申请")
    amount = order.net_paid if order.net_paid > 0 else order.amount
    inv = Invoice.objects.create(
        order=order,
        owner=order.owner,
        kind=kind or Invoice.Kind.PERSONAL,
        title=(title or order.owner.name)[:120],
        tax_no=(tax_no or "")[:40],
        email=(email or order.owner.email or "")[:254],
        amount=amount,
        status=Invoice.Status.ISSUED,
        issued_at=timezone.now(),
    )
    ensure_invoice_pdf(inv)
    return inv


def ensure_invoice_pdf(invoice: Invoice) -> Path:
    if invoice.pdf and invoice.pdf.name:
        return Path(invoice.pdf.path)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    # 使用内置字体，中文用拼音/英文混排标题 + Unicode 核心字段用 latin-1 可打印替代
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "PawStay Electronic Receipt", ln=True)
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"Receipt No: {invoice.receipt_no}", ln=True)
    pdf.cell(0, 8, f"Order: {invoice.order.order_no}", ln=True)
    pdf.cell(0, 8, f"Title: {_safe(invoice.title)}", ln=True)
    if invoice.tax_no:
        pdf.cell(0, 8, f"Tax No: {_safe(invoice.tax_no)}", ln=True)
    pdf.cell(0, 8, f"Pet: {_safe(invoice.order.pet.name)}", ln=True)
    pdf.cell(0, 8, f"Room: {_safe(invoice.order.room.display_name)}", ln=True)
    pdf.cell(
        0,
        8,
        f"Stay: {invoice.order.check_in.isoformat()} ~ {invoice.order.check_out.isoformat()} ({invoice.order.days} nights)",
        ln=True,
    )
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 12, f"Amount: CNY {invoice.amount:.2f}", ln=True)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 8, f"Issued at: {timezone.localtime(invoice.issued_at or timezone.now()).strftime('%Y-%m-%d %H:%M')}", ln=True)
    pdf.multi_cell(0, 6, "This is an electronic boarding receipt for accounting reference.")
    raw = pdf.output()
    invoice.pdf.save(f"{invoice.receipt_no}.pdf", ContentFile(bytes(raw)), save=True)
    if invoice.status != Invoice.Status.ISSUED:
        invoice.status = Invoice.Status.ISSUED
        invoice.issued_at = timezone.now()
        invoice.save(update_fields=["status", "issued_at"])
    return Path(invoice.pdf.path)


def _safe(text: str) -> str:
    return (text or "").encode("latin-1", "replace").decode("latin-1")
