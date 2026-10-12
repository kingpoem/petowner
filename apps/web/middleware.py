from django.db import DatabaseError, connection
from django.http import HttpResponse


class HealthCheckMiddleware:
    """/healthz 探活：置于中间件首位，绕过 ALLOWED_HOSTS 与 HTTPS 跳转，供容器编排和负载均衡使用。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != "/healthz":
            return self.get_response(request)
        try:
            connection.ensure_connection()
        except DatabaseError:
            return HttpResponse("database unavailable", status=503, content_type="text/plain")
        return HttpResponse("ok", content_type="text/plain")
