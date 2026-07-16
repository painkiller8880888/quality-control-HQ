from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    message = "管理者権限が必要です。"

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.role == "admin"
        )
