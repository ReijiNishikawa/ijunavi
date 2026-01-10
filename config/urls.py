"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from ijunavi import views as ijunavi_views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', ijunavi_views.chat_view, name='chat'),
    path('chat/history/', ijunavi_views.chat_history, name='history'),
    path('admin/', admin.site.urls),
    path('mypage/', ijunavi_views.mypage_view, name='mypage'),
    path('mypage/edit/', ijunavi_views.profile_edit_view, name='profile_edit'),
    path('bookmark/', ijunavi_views.bookmark_view, name='bookmark'),
    path('bookmark/add/', ijunavi_views.bookmark_add, name='bookmark_add'),
    path('bookmark/remove/', ijunavi_views.bookmark_remove, name='bookmark_remove'),
    path("bookmark/detail/<int:index>/", ijunavi_views.bookmark_detail, name="bookmark_detail"),
    path('accounts/', include('accounts.urls')),
    path('logout/', auth_views.LogoutView.as_view(next_page='chat'), name='logout'),

    # ✅ 追加：RAG進捗API
    path('rag/init/', ijunavi_views.rag_init, name='rag_init'),
    path('rag/progress/', ijunavi_views.rag_progress, name='rag_progress'),
    path('rag/recommend/', ijunavi_views.rag_recommend, name='rag_recommend'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
