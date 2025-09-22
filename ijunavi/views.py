from django.shortcuts import render, redirect
import random
from django.http import HttpResponse
from django.http import Http404
from django.utils import timezone

# Create your views here.

# 体験版：最初は固定の2メッセージ→年齢を聞く
INITIAL_BOT_MESSAGES = [
    "こんにちは！",
    "あなたにおすすめの場所を探します",
]
FIRST_QUESTION = "年齢を教えてください"

def top(request):
    return render(request, 'ijunavi/top.html')

def login_view(request):
    return render(request, 'ijunavi/login.html')

def signup_view(request):
    return render(request, 'ijunavi/signup.html')

# ここからチャット関連
def chat_view(request):
    """
    Q&A型の簡易チャット。
    - start: 初回ボット2通 + 「年齢を教えてください」
    - send: 年齢を受け取り、確認の返答を返す
    """
    chat_active = request.session.get("chat_active", False)
    messages = request.session.get("messages", [])
    step = request.session.get("step", 0)          # 0=未開始, 1=年齢待ち, 2=終了/次の質問待ち
    answers = request.session.get("answers", {})   # 回答保存（例: {"age": 20}）

    if request.method == "POST":
        action = request.POST.get("action")

        # 1) 開始：ボットの挨拶2通 → 年齢質問
        if action == "start":
            request.session["chat_active"] = True
            chat_active = True
            messages = []
            for m in INITIAL_BOT_MESSAGES:
                messages.append({"role": "bot", "text": m})
            messages.append({"role": "bot", "text": FIRST_QUESTION})
            step = 1  # 年齢待ち
            request.session.update({"messages": messages, "step": step, "answers": {}})

        # 2) ユーザー送信
        elif action == "send" and chat_active:
            user_msg = (request.POST.get("message") or "").strip()
            if user_msg:
                messages.append({"role": "user", "text": user_msg})

                # 年齢の受け取り
                if step == 1:
                    # 年齢を整数でパース
                    age_val = None
                    try:
                        age_val = int(''.join([c for c in user_msg if c.isdigit()]))
                    except Exception:
                        age_val = None

                    if age_val is None:
                        messages.append({"role": "bot", "text": "すみません、数字で年齢を教えてください。"})
                    else:
                        answers["age"] = age_val
                        messages.append({"role": "bot", "text": f"ありがとうございます。{age_val}歳ですね。"})
                        # この先の質問を増やす場合はここで messages.append(...) して step を更新
                        messages.append({"role": "bot", "text": "今回は体験版のためここまでです。次の質問を追加したい場合は教えてください。"})
                        step = 2

                    request.session["answers"] = answers

                # 以降の拡張用（step==2 以降で追加質問を出す等）
                else:
                    messages.append({"role": "bot", "text": "次の質問は未設定です。追加したい質問を教えてください。"})
                    step = 2

                request.session["messages"] = messages
                request.session["step"] = step

        # 3) リセット
        elif action == "reset":
            for k in ("chat_active", "messages", "step", "answers"):
                if k in request.session:
                    del request.session[k]
            return redirect("chat")

    return render(request, 'ijunavi/chat.html', {
        "chat_active": chat_active,
        "messages": messages,
        "step": step,
        "answers": answers,
    })


def chat_history(request):
    messages = request.session.get("messages", [])
    return render(request, 'ijunavi/history.html', {"messages": messages})

def _get_profile(request):
    """セッションからプロフィール取得（なければ仮データ）"""
    profile = request.session.get("profile")
    if not profile:
        profile = {
            "username": "ユーザー名",
            "email": "xxx@xx.xx",
            "image": None,  # 画像は未使用（プレースホルダ）
        }
        request.session["profile"] = profile
    return profile

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

def mypage_view(request):
    """マイページ（表示のみ）"""
    profile = _get_profile(request)

    # 簡易な「履歴・実績」：チャット履歴の最後2件をサンプル表示
    chat_msgs = request.session.get("messages", [])
    history_lines = []
    if chat_msgs:
        # 直近2件を抜粋（存在すれば）
        tail = chat_msgs[-2:] if len(chat_msgs) >= 2 else chat_msgs
        for m in tail:
            history_lines.append(f"{m.get('role','')} を保存しました（仮）")
    else:
        history_lines.append("履歴はまだありません")

    return render(request, 'ijunavi/mypage.html', {
        "profile": profile,
        "history_lines": history_lines,
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