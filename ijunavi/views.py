from django.shortcuts import render, redirect
import random
from django.http import HttpResponse
from django.http import Http404
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import re
import threading
from django.http import JsonResponse
from django.urls import reverse

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
    {"key": "age", "ask": "年齢を教えてください（数字のみ）", "choices": []},
    {"key": "style", "ask": "どんな暮らしが理想？", "choices": ["自然", "都市", "バランス"]},
    {"key": "climate", "ask": "好きな気候は？", "choices": ["暖かい", "涼しい", "こだわらない"]},
    {"key": "family", "ask": "家族構成は？", "choices": ["単身", "夫婦のみ", "子どものいる世帯", "二世帯"]},
    {"key": "else", "ask": "その他の条件を入力してください", "choices": []},
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
    family = answers.get("family", "")
    a_else = answers.get("else", "")

    prompt = f"""
    私の年齢は{age}歳です。
    家族構成は{family}です。
    理想の暮らしは「{style}」で、好きな気候は「{climate}」です。
    また{a_else}も考慮してください。
    これらの条件に最も合う地方移住先を提案し、その地域に関する情報を詳細に教えてください。
    """

    try:
        # RAG実行
        recommendation_result = rag_service.generate_recommendation(prompt)

        # headline から住所を抽出して map_address に格納
        headline = recommendation_result.get("headline", "")
        map_address = extract_address_from_headline(headline)
        recommendation_result["map_address"] = map_address

        return recommendation_result

    except Exception as e:
        print(f"RAGサービス呼び出しエラー: {e}")
        headline = "【エラー】情報取得に失敗しました"
        return {
            "headline": headline,
            "spots": ["システムエラーが発生しました。詳細はサーバーログを確認してください。"],
            "map_address": extract_address_from_headline(headline),
        }
    
# --- chat_view ---
def chat_view(request):
    chat_active = request.session.get("chat_active", False)
    messages = request.session.get("messages", [])
    step = request.session.get("step", -1)  # -1:未開始, 0..質問index, 100:結果表示
    answers = request.session.get("answers", {})
    result = request.session.get("result")

    if 0 <= step < len(QUESTIONS):
        question_data = QUESTIONS[step]
    else:
        question_data = None

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
        elif action == "send" and chat_active and 0 <= step < len(QUESTIONS):
            user_msg = _normalize(request.POST.get("choice") or request.POST.get("message"))

            if user_msg:
                messages.append({"role": "user", "text": user_msg})
                qkey = QUESTIONS[step]["key"]

                # 年齢のバリデーション
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
                    result = _get_rag_recommendation(answers)
                    messages.append({
                        "role": "bot",
                        "text": "ありがとうございます。条件に合う候補を用意しました。"
                    })
                    step = 100

                request.session.update({
                    "messages": messages,
                    "step": step,
                    "answers": answers,
                    "result": result,
                })

            return redirect("chat")

        # リセットロジック
        elif action == "reset":
            for k in ("chat_active", "messages", "step", "answers", "result"):
                request.session.pop(k, None)
            return redirect("chat")

    return render(request, "ijunavi/chat.html", {
        "chat_active": chat_active,
        "messages": messages,
        "question_data": question_data,
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

@login_required
def bookmark_view(request):
    """ブックマーク一覧"""
    bookmarks = _get_bookmarks(request)
    return render(request, 'ijunavi/bookmark.html', {
        "bookmarks": bookmarks,
    })

@login_required
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

@login_required
def bookmark_add(request):
    """ブックマーク追加（POST）"""
    if request.method != "POST":
        return redirect("bookmark")

    title = request.POST.get("title", "").strip()
    address = request.POST.get("address", "").strip()

    spots_raw = request.POST.get("spots", "")
    spots = [s for s in spots_raw.split("|||") if s.strip()] if spots_raw else []

    if not title:
        return redirect("bookmark")

    bookmarks = _get_bookmarks(request)

    # sessionの配列indexを使って detail_url を作る（追加後の番号）
    new_index = len(bookmarks)
    detail_url = f"/bookmark/detail/{new_index}/"

    bookmarks.append({
        "title": title or "(タイトル未設定)",
        "address": address or "",
        "spots": spots,  # ★これがないと詳細で落ちる
        "detail_url": detail_url,
        "saved_at": timezone.localtime().strftime("%Y-%m-%d %H:%M"),
    })

    request.session["bookmarks"] = bookmarks
    request.session.modified = True
    return redirect("bookmark")

def extract_address_from_headline(headline: str) -> str:
    """
    RAG の見出しテキストから地図用の住所を取り出す。
    例:
      最も推奨する地域は「南城市（沖縄県）」です。
      → 沖縄県南城市
    """

    if not headline:
        return ""

    # まず「〜」の中身を取る（「南城市（沖縄県）」など）
    m = re.search(r'「(.+?)」', headline)
    if m:
        name = m.group(1).strip()  # '南城市（沖縄県）'

        # 「市（県）」のようなパターンを分解
        m2 = re.match(r'(.+)[(（](.+?)[)）]', name)
        if m2:
            city = m2.group(1).strip()   # 南城市
            pref = m2.group(2).strip()   # 沖縄県
            return f"{pref}{city}"       # 沖縄県南城市

        # かっこが無ければそのまま住所として使う
        return name

    # 「」が無い場合は「○○県○○市」パターンを探す
    m = re.search(r'(..[都道府県].+?[市区町村])', headline)
    if m:
        return m.group(1).strip()

    # 何も取れなかったら、念のため全文を返す
    return headline.strip()

@login_required
def bookmark_detail(request, index):
    bookmarks = _get_bookmarks(request)

    try:
        index = int(index)
        data = bookmarks[index]
    except:
        raise Http404("ブックマークが存在しません")

    return render(request, "ijunavi/bookmark_detail.html", {
        "title": data.get("title", ""),
        "address": data.get("address", ""),
        "spots": data.get("spots", []),
    })

_rag_thread = None

def rag_init(request):
    global _rag_thread

    st = rag_service.get_rag_status()
    if st.get("state") in ("building", "ready"):
        return JsonResponse(st)

    def runner():
        try:
            rag_service.initialize_rag()
        except Exception:
            pass

    _rag_thread = threading.Thread(target=runner, daemon=True)
    _rag_thread.start()

    return JsonResponse(rag_service.get_rag_status())

def rag_progress(request):
    return JsonResponse(rag_service.get_rag_status())

def rag_recommend(request):
    answers = request.session.get("answers", {})
    result = _get_rag_recommendation(answers)
    request.session["result"] = result
    request.session["step"] = 100
    request.session.modified = True
    return JsonResponse({"ok": True, "redirect_url": reverse("chat")})

