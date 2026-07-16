from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from quality.models import History, InspectionSession, InspectionTarget, Job, LayoutMaster, User, UserSetting


class Command(BaseCommand):
    help = "初期adminを作成し、所有者未設定の既存業務データを移管します。"

    def add_arguments(self, parser):
        parser.add_argument("--login-name", required=True)
        parser.add_argument("--display-name")

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(role=User.Role.ADMIN).exists():
            raise CommandError("adminは既に存在します。")
        login_name = options["login_name"].strip()
        if User.objects.filter(login_name=login_name).exists():
            raise CommandError("指定されたIDは既に存在します。")
        password = getpass("Password: ")
        confirmation = getpass("Password (again): ")
        if password != confirmation:
            raise CommandError("パスワードが一致しません。")
        if len(password) < 8:
            raise CommandError("パスワードは8文字以上で指定してください。")
        user = User(login_name=login_name, display_name=options.get("display_name") or login_name, role=User.Role.ADMIN)
        user.set_password(password)
        user.save()
        UserSetting.objects.create(user=user)
        InspectionSession.objects.filter(owner_user__isnull=True).update(owner_user=user)
        InspectionSession.objects.filter(created_by__isnull=True).update(created_by=user)
        InspectionSession.objects.filter(updated_by__isnull=True).update(updated_by=user)
        InspectionSession.objects.filter(deleted_at__isnull=False, deleted_by__isnull=True).update(deleted_by=user)
        InspectionTarget.objects.filter(created_by__isnull=True).update(created_by=user)
        InspectionTarget.objects.filter(updated_by__isnull=True).update(updated_by=user)
        InspectionTarget.objects.filter(deleted_at__isnull=False, deleted_by__isnull=True).update(deleted_by=user)
        History.objects.filter(created_by__isnull=True).update(created_by=user)
        History.objects.filter(updated_by__isnull=True).update(updated_by=user)
        History.objects.filter(deleted_at__isnull=False, deleted_by__isnull=True).update(deleted_by=user)
        Job.objects.filter(created_by__isnull=True).update(created_by=user)
        Job.objects.filter(updated_by__isnull=True).update(updated_by=user)
        Job.objects.filter(deleted_at__isnull=False, deleted_by__isnull=True).update(deleted_by=user)
        LayoutMaster.objects.filter(owner_user__isnull=True).update(owner_user=user)
        self.stdout.write(self.style.SUCCESS(f"初期admin '{login_name}' を作成しました。"))
