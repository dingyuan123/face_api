"""创建仅用于开发/运营后台的管理员登录账号。"""

from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError, CommandParser

from backend.accounts.models import User
from backend.accounts.services import hash_phone, mask_phone, normalize_phone


class Command(BaseCommand):
    help = "创建或提升一个可登录 Django Admin 的开发管理员账号。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--phone", required=True, help="管理员登录手机号")
        parser.add_argument("--password", required=True, help="管理员登录密码")

    def handle(self, *args: object, **options: object) -> None:
        phone = normalize_phone(str(options["phone"]))
        password = str(options["password"])
        if len(password) < 12:
            raise CommandError("管理员密码至少需要 12 个字符。")
        phone_hash = hash_phone(phone)
        user = User.objects.filter(phone_hash=phone_hash).first()
        if user is None:
            user = User.objects.create(
                phone_hash=phone_hash,
                phone_masked=mask_phone(phone),
                password=make_password(password),
                status=User.Status.ACTIVE,
                is_staff=True,
            )
        else:
            user.password = make_password(password)
            user.status = User.Status.ACTIVE
            user.is_staff = True
            user.save(update_fields=["password", "status", "is_staff", "updated_at"])
        self.stdout.write(
            self.style.SUCCESS(f"管理员账号已就绪: {mask_phone(phone)}；登录用户名使用完整手机号。")
        )
