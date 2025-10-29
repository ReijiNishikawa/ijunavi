from django.shortcuts import render, redirect
import random
from django.http import HttpResponse
from django.http import Http404
from django.utils import timezone

# 🚨 変更点: rag_service.py から回答生成関数をインポート
from . import rag_service 

# Create your views here.

INITIAL_BOT_MESSAGES = [
    "こんにちは！",
    "あなたにおすすめの場所を探します",
]

QUESTIONS = [
    {"key": "age",   "ask": "年齢を教えてください（数字のみ）"},
    {"key": "style",  "ask": "どんな暮らしが理想？（自然 / 都市 / バランス）"},
    {"key": "climate", "ask": "好きな気候は？（暖かい / 涼しい / こだわらない）"},
]

def _normalize(s: str) -> str:
    return (s or "").strip()

def _int_from_text(s: str):
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None

# 🚨 変更点: 既存の _recommend 関数を削除し、RAGサービスを呼び出す関数に置き換え

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
    # 応答は辞書形式 { "headline": "...", "spots": ["...", "..."] } で返されることを期待
    try:
        recommendation_result = rag_service.generate_recommendation(prompt)
        return recommendation_result
    except Exception as e:
        # RAGサービスが失敗した場合のフォールバック
        print(f"RAGサービス呼び出しエラー: {e}")
        return {
            "headline": "【エラー】情報取得に失敗しました",
            "spots": ["システムエラーが発生しました。", "初期の_recommend関数ロジックが使用されます。（仮）"],
        }
    
# --- chat_view 以降の関数は変更なし ---
# ...
def chat_view(request):
    chat_active = request.session.get("chat_active", False)
    messages = request.session.get("messages", [])
    step = request.session.get("step", -1) # -1:未開始, 0..質問index, 100:結果表示
    answers = request.session.get("answers", {})
    result = request.session.get("result")

    if request.method == "POST":
        action = request.POST.get("action")

        # 開始ロジック (変更なし)
        if action == "start":
            # ... (中略) ...
            request.session.update({
                "chat_active": chat_active,
                "messages": messages,
                "step": step,
                "answers": answers,
                "result": result,
            })
            return redirect("chat") # リダイレクトを追加して二重送信を防ぐ（任意）

        # 送信ロジック
        elif action == "send" and chat_active and step >= 0 and step < len(QUESTIONS):
            user_msg = _normalize(request.POST.get("message"))
            if user_msg:
                messages.append({"role": "user", "text": user_msg})

                qkey = QUESTIONS[step]["key"]
                # ... (入力バリデーションロジック: 変更なし) ...
                
                # 次の質問 or 結果表示
                if step < len(QUESTIONS):
                    messages.append({"role": "bot", "text": QUESTIONS[step]["ask"]})
                else:
                    # 🚨 変更点: RAGサービスから結果を取得
                    result = _get_rag_recommendation(answers) 
                    messages.append({"role": "bot", "text": "ありがとうございます。条件に合う候補を用意しました。"})
                    step = 100 # 結果表示段階

                request.session.update({
                    "messages": messages, "step": step, "answers": answers, "result": result
                })
            return redirect("chat") # リダイレクトを追加

        # リセットロジック (変更なし)
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

# ... (top, chat_history, mypage_view, bookmark_view, bookmark_remove 関数は変更なし) ...