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


INITIAL_BOT_MESSAGES = [
    "こんにちは！",
    "あなたにおすすめの場所を探します",
]

QUESTIONS = [
    {"key": "age", "ask": "年齢を教えてください（数字のみ）"},

    {"key": "style", "ask": "どんな暮らしが理想？",
     "choices": ["自然", "都市", "バランス"]},

    {"key": "climate", "ask": "好きな気候は？",
     "choices": ["暖かい", "涼しい", "こだわらない"]},

    {"key": "family", "ask": "家族構成は？",
     "choices": ["単身", "夫婦のみ", "子供がいる"]},

    # ★ 子供がいる場合のみ聞く質問（通常はスキップ）
    {"key": "child_grade", "ask": "お子さんは何年生ですか？（例：小3 / 中1 / 高2 など）",
     "condition": {"family": "子供がいる"}},

    {"key": "else", "ask": "その他の条件を入力してください"},
]


def get_next_question(step, answers):
    """
    step(質問index) から先で、条件を満たす「次に出すべき質問」を返す。
    条件を満たさない質問はスキップ。
    """
    while step < len(QUESTIONS):
        q = QUESTIONS[step]

        if "condition" not in q:
            return step, q

        cond_key = list(q["condition"].keys())[0]
        cond_value = q["condition"][cond_key]

        if answers.get(cond_key) == cond_value:
            return step, q

        step += 1

    return None, None


def _normalize(s: str) -> str:
    return (s or "").strip()


def _int_from_text(s: str):
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None


def _get_question_by_step(step: int):
    if step is None:
        return None
    if 0 <= step < len(QUESTIONS):
        return QUESTIONS[step]
    return None


def _validate_choice(q: dict, user_msg: str):
    """
    choices がある質問の入力を検証。
    OKなら (True, user_msg) / NGなら (False, エラーメッセージ)
    """
    choices = q.get("choices")
    if not choices:
        return True, user_msg

    if user_msg in choices:
        return True, user_msg

    # 選択肢の見せ方を統一
    pretty = "」「".join(choices)
    return False, f"よくわかりません。「{pretty}」から選んでください。"


def _get_rag_recommendation(answers):
    """
    RAGサービスを呼び出し、ユーザーの回答に基づいて移住先を提案する。
    """
    age = answers.get("age")
    style = answers.get("style", "")
    climate = answers.get("climate", "")
    family = answers.get("family", "")
    child_grade = answers.get("child_grade", "")
    a_else = answers.get("else", "")

    # 子供がいる時だけ学年を含める
    child_line = ""
    if family == "子供がいる" and child_grade:
        child_line = f"子供の学年は「{child_grade}」です。"

    prompt = f"""
私の年齢は{age}歳です。
家族構成は{family}です。
{child_line}
理想の暮らしは「{style}」で、好きな気候は「{climate}」です。
また{a_else}も考慮してください。
これらの条件に最も合う地方移住先を提案し、その地域に関する情報を詳細に教えてください。
回答をそのまま出力するため、特殊文字は使用しないで下さい。
内容の種類ごとに改行をするようにしてください。
""".strip()

    try:
        recommendation_result = rag_service.generate_recommendation(prompt)

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


def chat_view(request):
    chat_active = request.session.get("chat_active", False)
    messages_sess = request.session.get("messages", [])
    step = request.session.get("step", -1)  # -1:未開始, 0..質問index, 100:結果表示
    answers = request.session.get("answers", {})
    result = request.session.get("result")

    if request.method == "POST":
        action = request.POST.get("action")

        # 開始
        if action == "start":
            chat_active = True
            messages_sess = [{"role": "bot", "text": msg} for msg in INITIAL_BOT_MESSAGES]
            answers = {}
            result = None

            # 最初の質問を condition 対応で決める（念のため）
            step, q = get_next_question(0, answers)
            if q:
                messages_sess.append({"role": "bot", "text": q["ask"]})
            else:
                step = 100

            request.session.update({
                "chat_active": chat_active,
                "messages": messages_sess,
                "step": step,
                "answers": answers,
                "result": result,
            })
            return redirect("chat")

        # 送信
        elif action == "send" and chat_active and 0 <= step < len(QUESTIONS):
            is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
            bot_messages = []

            user_msg = _normalize(request.POST.get("message"))
            if not user_msg:
                if is_ajax:
                    return JsonResponse({"ok": False})
                return redirect("chat")

            # ユーザー発言を保存
            messages_sess.append({"role": "user", "text": user_msg})

            q = _get_question_by_step(step)
            if not q:
                if is_ajax:
                    return JsonResponse({"ok": False})
                return redirect("chat")

            qkey = q["key"]

            # 1) age は数字強制
            if qkey == "age":
                age_val = _int_from_text(user_msg)
                if age_val is None:
                    msg = "よくわかりません。年齢を数字で入力してください。"
                    messages_sess.append({"role": "bot", "text": msg})
                    request.session.update({"messages": messages_sess, "step": step, "answers": answers, "result": result})
                    if is_ajax:
                        return JsonResponse({"ok": True, "bot_messages": [msg]})
                    return redirect("chat")
                answers[qkey] = age_val

            # 2) choicesがある質問（style/climate/family）は共通で検証
            elif "choices" in q:
                ok, val_or_msg = _validate_choice(q, user_msg)
                if not ok:
                    msg = val_or_msg
                    messages_sess.append({"role": "bot", "text": msg})
                    request.session.update({"messages": messages_sess, "step": step, "answers": answers, "result": result})
                    if is_ajax:
                        return JsonResponse({"ok": True, "bot_messages": [msg]})
                    return redirect("chat")
                answers[qkey] = val_or_msg

            # 3) child_grade / else など自由入力
            else:
                answers[qkey] = user_msg

            # 次の質問へ（conditionを考慮してスキップ）
            next_step, next_q = get_next_question(step + 1, answers)

            # まだ質問がある
            if next_q:
                step = next_step
                messages_sess.append({"role": "bot", "text": next_q["ask"]})
                bot_messages.append(next_q["ask"])
                request.session.update({"messages": messages_sess, "step": step, "answers": answers, "result": result})

                if is_ajax:
                    return JsonResponse({"ok": True, "bot_messages": bot_messages})
                return redirect("chat")

            # 質問終了 → RAGへ（重いので進捗表示）
            done_msg = "おすすめを作成中です…（しばらくお待ちください）"
            messages_sess.append({"role": "bot", "text": done_msg})
            bot_messages.append(done_msg)

            result = None
            step = 99  # 作成中ステータス

            request.session.update({"messages": messages_sess, "step": step, "answers": answers, "result": result})

            if is_ajax:
                return JsonResponse({
                    "ok": True,
                    "bot_messages": bot_messages,
                    "need_rag_progress": True,
                    "init_url": reverse("rag_init"),
                    "progress_url": reverse("rag_progress"),
                    "recommend_url": reverse("rag_recommend"),
                })
            return redirect("chat")

        # リセット
        elif action == "reset":
            for k in ("chat_active", "messages", "step", "answers", "result"):
                if k in request.session:
                    del request.session[k]
            return redirect("chat")

    return render(request, "ijunavi/chat.html", {
        "chat_active": chat_active,
        "messages": messages_sess,
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
    messages_sess = request.session.get("messages", [])
    return render(request, 'ijunavi/history.html', {"messages": messages_sess})


def _get_bookmarks(request):
    """セッションからブックマーク一覧取得（例データ）"""
    bms = request.session.get("bookmarks")
    if bms is None:
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

    new_index = len(bookmarks)
    detail_url = f"/bookmark/detail/{new_index}/"

    bookmarks.append({
        "title": title or "(タイトル未設定)",
        "address": address or "",
        "spots": spots,
        "detail_url": detail_url,
        "saved_at": timezone.localtime().strftime("%Y-%m-%d %H:%M"),
    })

    request.session["bookmarks"] = bookmarks
    request.session.modified = True
    return redirect("bookmark")


def _parse_rag_blocks(text: str) -> dict:
    text = _format_rag_text(text)

    def pick(pattern: str):
        m = re.search(pattern, text, flags=re.DOTALL)
        return m.group(1).strip() if m else ""

    parsed = {
        "conclusion": pick(r"■結論[:：]?\s*(.*?)(?=\n\s*■理由1|\n\s*■理由２|\n\s*■理由2|\n\s*■補足・アドバイス|\n\s*---\s*参照情報\s*---|\Z)"),
        "reason1": pick(r"■理由1.*?\n(.*?)(?=\n\s*■理由2|\n\s*■理由２|\n\s*■補足・アドバイス|\n\s*---\s*参照情報\s*---|\Z)"),
        "reason2": pick(r"■理由2.*?\n(.*?)(?=\n\s*■理由3|\n\s*■補足・アドバイス|\n\s*---\s*参照情報\s*---|\Z)"),
        "reason3": pick(r"■理由3.*?\n(.*?)(?=\n\s*■補足・アドバイス|\n\s*---\s*参照情報\s*---|\Z)"),
        "advice": pick(r"■補足・アドバイス\s*\n(.*?)(?=\n\s*---\s*参照情報\s*---|\Z)"),
        "refs": pick(r"---\s*参照情報\s*---\s*\n(.*?)(?=\Z)"),
    }
    return parsed


def _format_rag_text(s: str) -> str:
    if not isinstance(s, str):
        return s

    s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")
    s = re.sub(r"[ \t\u3000]*■", "■", s)

    s = re.sub(r"(?<!\n)■結論", r"\n\n■結論", s)
    s = re.sub(r"(?<!\n)■理由(\d+)", r"\n\n■理由\1", s)
    s = re.sub(r"(?<!\n)■補足・アドバイス", r"\n\n■補足・アドバイス", s)
    s = re.sub(r"(?<!\n)---\s*参照情報\s*---", r"\n\n--- 参照情報 ---", s)

    s = re.sub(r"(?<!\n)\[参照元\]", r"\n[参照元]", s)
    s = re.sub(r"\n{3,}", "\n\n", s)

    return s.strip()


def extract_address_from_headline(headline: str) -> str:
    if not headline:
        return ""

    m = re.search(r'「(.+?)」', headline)
    if m:
        name = m.group(1).strip()  # '南城市（沖縄県）'

        m2 = re.match(r'(.+)[(（](.+?)[)）]', name)
        if m2:
            city = m2.group(1).strip()
            pref = m2.group(2).strip()
            return f"{pref}{city}"

        return name

    m = re.search(r'(..[都道府県].+?[市区町村])', headline)
    if m:
        return m.group(1).strip()

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

    if isinstance(result, dict):
        if isinstance(result.get("headline"), str):
            result["headline"] = _format_rag_text(result["headline"])

        if isinstance(result.get("spots"), list):
            result["spots"] = [
                (_format_rag_text(s) if isinstance(s, str) else s)
                for s in result["spots"]
            ]

            if result["spots"]:
                result["parsed"] = _parse_rag_blocks(result["spots"][0])

    request.session["result"] = result
    request.session["step"] = 100
    request.session.modified = True
    return JsonResponse({"ok": True, "redirect_url": reverse("chat")})
