import logging
from pathlib import Path

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.http import FileResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.utils.decorators import method_decorator
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from PIL import Image, UnidentifiedImageError

from .models import AuditLog, User, UserSetting
from .permissions import IsAdmin


logger = logging.getLogger(__name__)


def delete_avatar_safely(storage, name):
    try:
        storage.delete(name)
    except Exception:
        logger.warning("Failed to delete replaced avatar.", exc_info=True)


def user_payload(user, *, include_avatar=False):
    setting, _ = UserSetting.objects.get_or_create(user=user)
    return {
        "id": user.user_id,
        "login_name": user.login_name,
        "display_name": user.display_name,
        "avatar_url": (
            f"/api/me/avatar/?v={int(user.updated_at.timestamp() * 1_000_000)}"
            if include_avatar and user.avatar else None
        ),
        "role": user.role,
        "settings": {
            "theme": setting.theme,
            "browser_settings_imported": setting.browser_settings_imported,
        },
    }


class CredentialsSerializer(serializers.Serializer):
    login_name = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"authenticated": False})
        return Response({"authenticated": True, "user": user_payload(request.user, include_avatar=True)})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["login_name"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response({"detail": "IDまたはパスワードが正しくありません。"}, status=status.HTTP_401_UNAUTHORIZED)
        login(request, user)
        AuditLog.objects.create(user=user, operation="login", table_name="users", record_id=str(user.pk))
        return Response({"user": user_payload(user, include_avatar=True)})


@method_decorator(csrf_protect, name="dispatch")
class RegisterView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = CredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        login_name = serializer.validated_data["login_name"].strip()
        if User.objects.filter(login_name=login_name).exists():
            return Response({"login_name": ["このIDは既に使用されています。"]}, status=status.HTTP_400_BAD_REQUEST)
        user = User(
            login_name=login_name,
            display_name=serializer.validated_data.get("display_name") or login_name,
            role=User.Role.WORKER,
        )
        user.set_password(serializer.validated_data["password"])
        user.save()
        UserSetting.objects.create(user=user)
        AuditLog.objects.create(user=user, operation="register", table_name="users", record_id=str(user.pk))
        login(request, user, backend="quality.authentication.LoginNameBackend")
        return Response({"user": user_payload(user, include_avatar=True)}, status=status.HTTP_201_CREATED)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        AuditLog.objects.create(user=user, operation="logout", table_name="users", record_id=str(user.pk))
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserSettingView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        setting, _ = UserSetting.objects.get_or_create(user=request.user)
        if "theme" in request.data:
            setting.theme = str(request.data["theme"])[:32]
        setting.browser_settings_imported = True
        setting.save()
        AuditLog.objects.create(user=request.user, operation="update", table_name="user_settings", record_id=str(request.user.pk))
        return Response(user_payload(request.user, include_avatar=True)["settings"])


class AvatarView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        avatar = request.user.avatar
        if not avatar or not avatar.name:
            return Response({"detail": "Avatar is not registered."}, status=status.HTTP_404_NOT_FOUND)

        suffix = avatar.name.rsplit(".", 1)[-1].lower() if "." in avatar.name else ""
        content_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
        content_type = content_types.get(suffix)
        if content_type is None:
            return Response({"detail": "Avatar is not available."}, status=status.HTTP_404_NOT_FOUND)

        try:
            image = avatar.storage.open(avatar.name, "rb")
        except FileNotFoundError:
            return Response({"detail": "Avatar is not available."}, status=status.HTTP_404_NOT_FOUND)
        except OSError:
            return Response({"detail": "Avatar storage is unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        response = FileResponse(image, content_type=content_type, as_attachment=False)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Disposition"] = "inline"
        return response


class ProfileSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    avatar = serializers.ImageField(required=False, allow_null=True)
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password_confirm = serializers.CharField(write_only=True, required=False, allow_blank=True)

    def validate_avatar(self, avatar):
        if avatar is None:
            return avatar
        if avatar.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("画像は5MB以下にしてください。")
        if avatar.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise serializers.ValidationError("JPEG、PNG、WebP形式の画像を選択してください。")
        try:
            image = Image.open(avatar)
            image_format = image.format
            image.verify()
        except (UnidentifiedImageError, OSError):
            raise serializers.ValidationError("JPEG, PNG, or WebP image data is required.")
        finally:
            avatar.seek(0)
        formats = {
            "JPEG": (".jpg", "image/jpeg"),
            "PNG": (".png", "image/png"),
            "WEBP": (".webp", "image/webp"),
        }
        if image_format not in formats:
            raise serializers.ValidationError("JPEG, PNG, or WebP image data is required.")
        extension, content_type = formats[image_format]
        avatar.name = f"{Path(avatar.name).stem}{extension}"
        avatar.content_type = content_type
        return avatar

    def validate(self, attrs):
        password_fields = {"current_password", "new_password", "new_password_confirm"}
        if password_fields.intersection(self.initial_data):
            missing = [field for field in password_fields if not attrs.get(field)]
            if missing:
                raise serializers.ValidationError({field: "パスワード変更時は3項目すべて入力してください。" for field in missing})
            if not self.context["request"].user.check_password(attrs["current_password"]):
                raise serializers.ValidationError({"current_password": "現在のパスワードが正しくありません。"})
            if attrs["new_password"] != attrs["new_password_confirm"]:
                raise serializers.ValidationError({"new_password_confirm": "新しいパスワードが一致しません。"})
            if len(attrs["new_password"]) < 8:
                raise serializers.ValidationError({"new_password": "新しいパスワードは8文字以上にしてください。"})
        return attrs


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request):
        serializer = ProfileSerializer(data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = User.objects.select_for_update().get(pk=request.user.pk)
        old_avatar_name = user.avatar.name if user.avatar else ""
        old_avatar_storage = user.avatar.storage if old_avatar_name else None
        changed_fields = []
        if "display_name" in serializer.validated_data:
            user.display_name = serializer.validated_data["display_name"]
            changed_fields.append("display_name")
        if "avatar" in serializer.validated_data:
            user.avatar = serializer.validated_data["avatar"]
            changed_fields.append("avatar")
        if "new_password" in serializer.validated_data:
            user.set_password(serializer.validated_data["new_password"])
            changed_fields.append("password_hash")
        if changed_fields:
            user.save(update_fields=changed_fields + ["updated_at"])
        if "avatar" in changed_fields and old_avatar_name and old_avatar_name != user.avatar.name:
            transaction.on_commit(lambda: delete_avatar_safely(old_avatar_storage, old_avatar_name))
        if "new_password" in serializer.validated_data:
            login(request, user, backend="quality.authentication.LoginNameBackend")
        AuditLog.objects.create(user=user, operation="update", table_name="users", record_id=str(user.pk), details_json={"fields": changed_fields})
        return Response({"user": user_payload(user, include_avatar=True)})


class UserManagementView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response([user_payload(user) | {"is_active": user.is_active} for user in User.objects.order_by("login_name")])

    @transaction.atomic
    def patch(self, request, user_id):
        user = User.objects.select_for_update().get(pk=user_id)
        new_role = request.data.get("role", user.role)
        new_active = request.data.get("is_active", user.is_active)
        if new_role not in User.Role.values:
            return Response({"role": ["adminまたはworkerを指定してください。"]}, status=status.HTTP_400_BAD_REQUEST)
        removing_admin = user.role == User.Role.ADMIN and (new_role != User.Role.ADMIN or not new_active)
        if removing_admin and not User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(pk=user.pk).exists():
            return Response({"detail": "最後の有効なadminは降格・無効化できません。"}, status=status.HTTP_400_BAD_REQUEST)
        user.role = new_role
        user.is_active = bool(new_active)
        if "display_name" in request.data:
            user.display_name = str(request.data["display_name"])[:255]
        user.save()
        AuditLog.objects.create(user=request.user, operation="update", table_name="users", record_id=str(user.pk), details_json={"role": user.role, "is_active": user.is_active})
        return Response(user_payload(user) | {"is_active": user.is_active})
