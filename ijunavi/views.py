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

def _get_bookmarks(request):
    """セッションからブックマーク一覧取得（例データ）"""
    bms = request.session.get("bookmarks")
    if bms is None:
        # 初回は空。動作確認用にサンプルを入れたい場合は下のコメントを外す
        # bms = [{
        #   "title": "【地図サムネイル】施設名",
        #   "address": "住所：東京都○○区…",
        #   "saved_at": str(timezone.now())[:16],
        # }]
        bms = []
        request.session["bookmarks"] = bms
    return bms


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
    """ブックマーク一覧"""
    bookmarks = _get_bookmarks(request)
    return render(request, 'ijunavi/bookmark.html', {
        "bookmarks": bookmarks,
    })

def bookmark_remove(request):
    """ブックマーク解除（POST: index）"""
    if request.method == "POST":
        idx = request.POST.get("index")
        bookmarks = _get_bookmarks(request)
        try:
            i = int(idx)
            if 0 <= i < len(bookmarks):
                bookmarks.pop(i)
                request.session["bookmarks"] = bookmarks
        except Exception:
            pass
    return redirect("bookmark")

def bookmark_add(request):
    """ブックマーク追加（POST）"""
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        address = request.POST.get("address", "").strip()
        detail_url = request.POST.get("detail_url", "").strip()

        if not title:
            # タイトルがない場合は無視
            return redirect("bookmark")

        bookmarks = _get_bookmarks(request)
        bookmarks.append({
            "title": title or "(タイトル未設定)",
            "address": address or "",
            "detail_url": detail_url or "",
            "saved_at": timezone.localtime().strftime("%Y-%m-%d %H:%M"),
        })
        request.session["bookmarks"] = bookmarks
        request.session.modified = True
        return redirect("bookmark")
    return redirect("bookmark")

