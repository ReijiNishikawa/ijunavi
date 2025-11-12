# ijunavi/admin.py
from django.contrib import admin
from .models import Bookmark

@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "address", "detail_url", "created_at")
    search_fields = ("title", "address", "detail_url", "user__email")
    list_filter = ("created_at",)
