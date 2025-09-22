from django.shortcuts import render, redirect
import random
from django.http import HttpResponse
from django.http import Http404
from django.utils import timezone

# Create your views here.

INITIAL_BOT_MESSAGES = [
    "こんにちは！",
    "あなたにおすすめの場所を探します",
]

QUESTIONS = [
    {"key": "age",     "ask": "年齢を教えてください（数字のみ）"},
    {"key": "style",   "ask": "どんな暮らしが理想？（自然 / 都市 / バランス）"},
    {"key": "climate", "ask": "好きな気候は？（暖かい / 涼しい / こだわらない）"},
]

def _normalize(s: str) -> str:
    return (s or "").strip()

def _int_from_text(s: str):
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None

def _recommend(answers):
    age = answers.get("age")
    style = answers.get("style", "").lower()
    climate = answers.get("climate", "").lower()

    # ベース候補
    if "自然" in style or "nature" in style:
        if "涼" in climate:
            city = ("長野県", "松本市")
        elif "暖" in climate:
            city = ("宮崎県", "日南市")
        else:
            city = ("長野県", "安曇野市")
    elif "都市" in style or "city" in style:
        if "涼" in climate:
            city = ("北海道", "札幌市")
        elif "暖" in climate:
            city = ("福岡県", "福岡市")
        else:
            city = ("神奈川県", "横浜市")
    else:  # バランス
        if "涼" in climate:
            city = ("石川県", "金沢市")
        elif "暖" in climate:
            city = ("香川県", "高松市")
        else:
            city = ("宮城県", "仙台市")

    # 年齢による微調整（ゆるく）
    if isinstance(age, int):
        if age <= 25 and city[1] not in ("福岡市", "札幌市", "仙台市", "横浜市"):
            city = ("福岡県", "福岡市")
        if age >= 60 and ("都市" in style or "city" in style):
            city = ("静岡県", "三島市")

    # 簡易的な周辺施設サンプル
    spots = [
        "周辺の施設",
        "・スーパー / 病院 / 図書館",
        "・市民センター / 公園",
        "・主要駅（バス連携あり）",
    ]
    return {
        "pref": city[0],
        "city": city[1],
        "headline": f"{city[0]}{city[1]}の情報",
        "spots": spots,
    }

def chat_view(request):
    chat_active = request.session.get("chat_active", False)
    messages = request.session.get("messages", [])
    step = request.session.get("step", -1)  # -1:未開始, 0..質問index, 100:結果表示
    answers = request.session.get("answers", {})
    result = request.session.get("result")

    if request.method == "POST":
        action = request.POST.get("action")

        # 開始
        if action == "start":
            chat_active = True
            messages = []
            for m in INITIAL_BOT_MESSAGES:
                messages.append({"role": "bot", "text": m})
            messages.append({"role": "bot", "text": QUESTIONS[0]["ask"]})
            step = 0
            answers, result = {}, None
            request.session.update({
                "chat_active": chat_active,
                "messages": messages,
                "step": step,
                "answers": answers,
                "result": result,
            })

        # 送信
        elif action == "send" and chat_active and step >= 0 and step < len(QUESTIONS):
            user_msg = _normalize(request.POST.get("message"))
            if user_msg:
                messages.append({"role": "user", "text": user_msg})

                qkey = QUESTIONS[step]["key"]
                # 入力バリデーション
                if qkey == "age":
                    val = _int_from_text(user_msg)
                    if val is None:
                        messages.append({"role": "bot", "text": "すみません、数字で年齢を教えてください。"})
                    else:
                        answers["age"] = val
                        step += 1
                elif qkey == "style":
                    answers["style"] = user_msg
                    step += 1
                elif qkey == "climate":
                    answers["climate"] = user_msg
                    step += 1

                # 次の質問 or 結果表示
                if step < len(QUESTIONS):
                    messages.append({"role": "bot", "text": QUESTIONS[step]["ask"]})
                else:
                    result = _recommend(answers)
                    messages.append({"role": "bot", "text": "ありがとうございます。条件に合う候補を用意しました。"})
                    step = 100  # 結果表示段階

                request.session.update({
                    "messages": messages, "step": step, "answers": answers, "result": result
                })

        # リセット
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

def top(request):
    return render(request, 'ijunavi/top.html')

def login_view(request):
    return render(request, 'ijunavi/login.html')

def signup_view(request):
    return render(request, 'ijunavi/signup.html')

def chat_history(request):
    messages = request.session.get("messages", [])
    return render(request, 'ijunavi/history.html', {"messages": messages})