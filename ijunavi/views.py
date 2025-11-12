from django.shortcuts import render, redirect
import random
from django.http import HttpResponse
from django.http import Http404
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages

# 🚨 RAGサービスから回答生成関数をインポート
from . import rag_service 

# accountsアプリからProfileFormをインポート（mainブランチ側の追加）
from accounts.forms import ProfileForm
from django.views.decorators.http import require_POST
from .models import Bookmark

# Create your views here.

INITIAL_BOT_MESSAGES = [
    "こんにちは！",
    "あなたにおすすめの場所を探します",
]

QUESTIONS = [
    {"key": "age", "ask": "年齢を教えてください（数字のみ）"},
    {"key": "style", "ask": "どんな暮らしが理想？（自然 / 都市 / バランス）"},
    {"key": "climate", "ask": "好きな気候は？（暖かい / 涼しい / こだわらない）"},
]

def _normalize(s: str) -> str:
    return (s or "").strip()

def _int_from_text(s: str):
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None

def _get_rag_recommendation(answers):
    """
    RAGサービスを呼び出し、ユーザーの回答に基づいて移住先を提案する。
    """
    age = answers.get("age")
    style = answers.get("style", "")
    climate = answers.get("climate", "")

    # ユーザーの回答を統合したプロンプトを作成
    prompt = f"""
    私の年齢は{age}歳です。
    理想の暮らしは「{style}」で、好きな気候は「{climate}」です。
    これらの条件に最も合う地方移住先を提案し、その地域に関する情報を詳細に教えてください。
    """
    
    # rag_service.py に定義された回答生成関数を呼び出す
    try:
        recommendation_result = rag_service.generate_recommendation(prompt)
        return recommendation_result
    except Exception as e:
        # RAGサービスが失敗した場合のフォールバック
        print(f"RAGサービス呼び出しエラー: {e}")
        return {
            "headline": "【エラー】情報取得に失敗しました",
            "spots": ["システムエラーが発生しました。詳細はサーバーログを確認してください。"],
        }
    
# --- chat_view ---

def chat_view(request):
    chat_active = request.session.get("chat_active", False)
    messages = request.session.get("messages", [])
    step = request.session.get("step", -1) # -1:未開始, 0..質問index, 100:結果表示
    answers = request.session.get("answers", {})
    result = request.session.get("result")

    if request.method == "POST":
        action = request.POST.get("action")

        # 開始ロジック 
        if action == "start":
            chat_active = True
            messages = [{"role": "bot", "text": msg} for msg in INITIAL_BOT_MESSAGES]
            step = 0
            messages.append({"role": "bot", "text": QUESTIONS[step]["ask"]})
            answers = {}
            result = None
            
            request.session.update({
                "chat_active": chat_active,
                "messages": messages,
                "step": step,
                "answers": answers,
                "result": result,
            })
            return redirect("chat")

        # 送信ロジック
        elif action == "send" and chat_active and step >= 0 and step < len(QUESTIONS):
            user_msg = _normalize(request.POST.get("message"))
            if user_msg:
                messages.append({"role": "user", "text": user_msg})

                qkey = QUESTIONS[step]["key"]
                
                # 年齢のバリデーション (簡易版)
                if qkey == "age":
                    age_val = _int_from_text(user_msg)
                    if age_val is None:
                        messages.append({"role": "bot", "text": "年齢を数字で入力してください。"})
                    else:
                        answers[qkey] = age_val
                        step += 1
                else:
                    answers[qkey] = user_msg
                    step += 1

                # 次の質問 or 結果表示
                if step < len(QUESTIONS):
                    messages.append({"role": "bot", "text": QUESTIONS[step]["ask"]})
                else:
                    # 🚨 RAGサービスから結果を取得
                    result = _get_rag_recommendation(answers) 
                    messages.append({"role": "bot", "text": "ありがとうございます。条件に合う候補を用意しました。"})
                    step = 100 # 結果表示段階

                request.session.update({
                    "messages": messages, "step": step, "answers": answers, "result": result
                })
            return redirect("chat")

        # リセットロジック
        elif action == "reset":
            for k in ("chat_active", "messages", "step", "answers", "result"):
                if k in request.session:
                    del request.session[k]
            return redirect("chat")

    return render(request, "ijunavi/chat.html", {
        "chat_active": chat_active,
        "messages": messages,
        "step": step,
        "answers": answers,
        "result": result,
    })

# --- mainブランチ側の基本ビュー関数を統合 ---

def top(request):
    """トップページ"""
    return render(request, 'ijunavi/top.html')

def chat_history(request):
    """チャット履歴表示"""
    messages = request.session.get("messages", [])
    return render(request, 'ijunavi/history.html', {"messages": messages})


@login_required
def mypage_view(request):
    """ログイン中ユーザーのプロフィール表示"""
    return render(request, 'ijunavi/mypage.html', {
        "user": request.user,
    })


@login_required
def profile_edit_view(request):
    """プロフィール編集"""
    if request.method == "POST":
        # request.user が AbstractUser などのカスタムユーザーモデルを継承していることを前提とします
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "プロフィールを更新しました。")
            return redirect("mypage")
    else:
        form = ProfileForm(instance=request.user)

    return render(request, 'ijunavi/profile_edit.html', {
        "form": form,
    })

def bookmark_view(request):
    qs = Bookmark.objects.filter(user=request.user).order_by("-created_at")
    return render(request, 'ijunavi/bookmark.html', {"bookmarks": qs})

@require_POST
@login_required
def bookmark_remove(request, pk: int):
    try:
        bm = Bookmark.objects.get(pk=pk, user=request.user)
    except Bookmark.DoesNotExist:
        messages.error(request, "対象のブックマークが見つかりません。")
        return redirect("bookmark")
    bm.delete()
    messages.success(request, "ブックマークを削除しました。")
    return redirect("bookmark")

@require_POST
@login_required
def bookmark_add(request):
    title = (request.POST.get("title") or "").strip()
    address = (request.POST.get("address") or "").strip()
    detail_url = (request.POST.get("detail_url") or "").strip()

    if not title:
        messages.warning(request, "タイトルが空のため保存しませんでした。")
        return redirect("bookmark")

    # 重複防止（同一内容は1件に）
    _, created = Bookmark.objects.get_or_create(
        user=request.user, title=title, address=address, detail_url=detail_url
    )
    if created:
        messages.success(request, "ブックマークに保存しました。")
    else:
        messages.info(request, "同じ内容のブックマークがすでに存在します。")
    return redirect("bookmark")

