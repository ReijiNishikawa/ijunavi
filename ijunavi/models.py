from django.conf import settings
from django.db import models

class Bookmark(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookmarks")
    title = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    detail_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("user", "title", "address", "detail_url")]

    def __str__(self):
        return f"{self.title} ({self.user})"
