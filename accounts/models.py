from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager

# カスタムマネージャーを追加
class UsersManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("メールアドレスは必須です。")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuserには is_staff=True が必要です。")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuserには is_superuser=True が必要です。")

        return self.create_user(email, password, **extra_fields)


class Users(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(max_length=255, unique=True)
    username = models.CharField(max_length=150, blank=True)
    icon = models.FileField(null=True, upload_to="icon/")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    verification_token = models.UUIDField(null=True, blank=True)
    token_created_at = models.DateTimeField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)

    objects = UsersManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
