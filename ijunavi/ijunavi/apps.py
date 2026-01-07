from django.apps import AppConfig

# 地方移住コンシェルジュアプリの設定
class IjunaviConfig(AppConfig):
    # Django 3.2以降で推奨されるデフォルトの主キーの型
    default_auto_field = 'django.db.models.BigAutoField'
    
    # アプリケーション名
    name = 'ijunavi'

    # ここにRAG関連のロジックやインポートは記述しません。
    # すべてのロジックは rag_service.py に移動しました。
