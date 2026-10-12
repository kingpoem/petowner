class PermissionsPolicyMiddleware:
    """限制浏览器能力：仅允许本站调用摄像头（护理师拍照上传），其余敏感能力全部禁用。"""

    POLICY = "camera=(self), microphone=(), geolocation=(), payment=(), usb=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", self.POLICY)
        return response
