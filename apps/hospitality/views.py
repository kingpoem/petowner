from django.shortcuts import redirect


def service_menu(request):
    """兼容旧链接：增值服务已并入护理服务页。"""
    return redirect("web:care")
