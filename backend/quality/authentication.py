from .models import User
from rest_framework.authentication import SessionAuthentication


class ApiSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request):
        return "Session"


class LoginNameBackend:
    def authenticate(self, request, username=None, password=None, **kwargs):
        login_name = username or kwargs.get("login_name")
        if not login_name or password is None:
            return None
        try:
            user = User.objects.get(login_name=login_name)
        except User.DoesNotExist:
            return None
        if user.is_active and user.check_password(password):
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None
