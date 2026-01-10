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
import os

from . import rag_service
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

    {"key": "hospital", "ask": "通院頻度は？",
     "choices": ["1か月に一回以上", "通院していない"]},

    {"key": "family", "ask": "家族構成は？",
     "choices": ["単身", "夫婦のみ", "子供がいる"]},

    {"key": "child_grade", "ask": "お子さんは何年生ですか？（例：小3 / 中1 / 高2 など）",
     "condition": {"family": "子供がいる"}},

    {"key": "else", "ask": "その他の条件を入力してください"},
]


def get_next_question(step, answers):
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
    choices = q.get("choices")
    if not choices:
        return True, user_msg

    if user_msg in choices:
        return True, user_msg

    pretty = "」「".join(choices)
    return False, f"よくわかりません。「{pretty}」から選んでください。"


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

def _extract_place_from_conclusion_text(text: str) -> str:
    """
    ■結論の中身から「○○都道府県○○市区町村」だけを返す
    例: "(大分県宇佐市)" -> "大分県宇佐市"
        "大分県宇佐市 住みやすい" -> "大分県宇佐市"
    """
    if not text:
        return ""

    # ( ) or （ ）の中身があれば優先
    m = re.search(r"[（(]\s*([^）)\n]+)\s*[）)]", text)
    if m:
        candidate = m.group(1).strip()
    else:
        candidate = text.strip()

    # 先頭の「都道府県 + 市区町村」だけを抜く
    m2 = re.search(r"((?:..[都道府県])(?:[^ \n　]+?[市区町村]))", candidate)
    return m2.group(1).strip() if m2 else candidate


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

    # ★理由3が必ず出るようにする（空なら埋める）
    if not parsed["reason3"]:
        if parsed["reason2"]:
            parsed["reason3"] = parsed["reason2"]
        elif parsed["reason1"]:
            parsed["reason3"] = parsed["reason1"]
        else:
            parsed["reason3"] = "理由3の情報が取得できませんでした。別の条件でもう一度お試しください。"

    # ★結論から「都道府県 + 市区町村」だけを抽出して保持
    parsed["conclusion_place"] = _extract_place_from_conclusion_text(parsed.get("conclusion", ""))

    return parsed


def extract_address_from_headline(headline: str) -> str:
    if not headline:
        return ""

    m = re.search(r'「(.+?)」', headline)
    if m:
        name = m.group(1).strip()

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


def format_headline_display(headline: str) -> str:
    """
    表示用：必ず「○○県○○市/区/町/村」だけにする
    """
    if not headline:
        return ""

    # 「」の中があれば優先
    m = re.search(r'「(.+?)」', headline)
    s = m.group(1).strip() if m else headline.strip()

    # ■結論：( ... ) の形なら括弧中身
    m2 = re.search(r"■結論[:：]?\s*[（(](.+?)[）)]", s)
    if m2:
        s = m2.group(1).strip()

    # 先頭の都道府県 + 市区町村だけ
    m3 = re.search(r"((?:..[都道府県])(?:[^ \n　]+?[市区町村]))", s)
    return m3.group(1).strip() if m3 else s

def _get_rag_recommendation(answers):
    """
    RAGサービスを呼び出し、ユーザーの回答に基づいて移住先を提案する。
    """
    age = answers.get("age")
    style = answers.get("style", "")
    climate = answers.get("climate", "")
    family = answers.get("family", "")
    hospital = answers.get("hospital", "")
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
通院頻度は「{hospital}」です。
その他の条件：{a_else}

【スーパーに関する要望（重要）】
- tenpo2511.csv の情報をもとに、提案地域および周辺地域の「スーパーの多さ」「日常の買い物のしやすさ」を説明してください。
- 具体的な店舗数や数値は一切書かないでください。
- 「○店舗」「店舗数」「数字」が含まれる表現は禁止です。
- 「比較的多い」「買い物に困りにくい」などの定性的な表現のみを使ってください。

【子育て・医療に関する条件】
- 子供の学年は「{child_grade}」です。学校が必要だと判断した場合、学校が多い地区を優先してください。
- 必要だと判断した場合、医療機関へのアクセスが良い地区を優先してください。

これらの条件に最も合う地方移住先を1つだけ提案し、その地域について説明してください。

【必須出力形式】
■結論：(必ず「○○都/道/府/県○○市/区/町/村」のみを書く。要約文は入れない)
■理由1
(スーパー・買い物環境について必ず触れる。数値は禁止)
■理由2
(別の観点の理由)
■理由3
(別の観点の理由)
■補足・アドバイス
(注意点など)

回答はそのまま画面に表示されます。
特殊文字は使用せず、内容の区切りごとに改行してください。
""".strip()

    try:
        recommendation_result = rag_service.generate_recommendation(prompt)

        headline = recommendation_result.get("headline", "") or ""
        headline = _format_rag_text(headline)

        # ★表示用（都道府県○○市の○○）
        recommendation_result["headline"] = headline
        recommendation_result["headline_display"] = format_headline_display(headline)

        # map は display を優先
        recommendation_result["map_address"] = (
            recommendation_result["headline_display"]
            or extract_address_from_headline(headline)
        )

        return recommendation_result

    except Exception as e:
        print(f"RAGサービス呼び出しエラー: {e}")
        headline = "【エラー】情報取得に失敗しました"
        return {
            "headline": headline,
            "headline_display": headline,
            "spots": ["システムエラーが発生しました。詳細はサーバーログを確認してください。"],
            "map_address": extract_address_from_headline(headline),
            "source_files": [],
        }


def chat_view(request):
    chat_active = request.session.get("chat_active", False)
    messages_sess = request.session.get("messages", [])
    step = request.session.get("step", -1)  # -1:未開始, 0..質問index, 99:作成中, 100:結果表示
    answers = request.session.get("answers", {})
    result = request.session.get("result")

    display_name = (
        request.user.username
        if request.user.is_authenticated and request.user.username
        else "あなた"
    )
    BOT_NAME = "いじゅナビ"

    def add_bot(msg_list, text):
        msg_list.append({"role": "bot", "sender": BOT_NAME, "text": text})

    def add_user(msg_list, text):
        msg_list.append({"role": "user", "sender": display_name, "text": text})

    def get_choices_for_step(step_value):
        q = _get_question_by_step(step_value)
        return (q.get("choices", []) if q else []) or []

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "start":
            chat_active = True
            messages_sess = []
            answers = {}
            result = None

            for msg in INITIAL_BOT_MESSAGES:
                add_bot(messages_sess, msg)

            step, q = get_next_question(0, answers)
            if q:
                add_bot(messages_sess, q["ask"])
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

        elif action == "send" and chat_active and 0 <= step < len(QUESTIONS):
            is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
            bot_messages = []

            user_msg = _normalize(request.POST.get("message"))
            if not user_msg:
                if is_ajax:
                    return JsonResponse({"ok": False})
                return redirect("chat")

            add_user(messages_sess, user_msg)

            q = _get_question_by_step(step)
            if not q:
                if is_ajax:
                    return JsonResponse({"ok": False})
                return redirect("chat")

            qkey = q["key"]

            if qkey == "age":
                age_val = _int_from_text(user_msg)
                if age_val is None:
                    msg = "よくわかりません。年齢を数字で入力してください。"
                    add_bot(messages_sess, msg)
                    request.session.update({"messages": messages_sess, "step": step, "answers": answers, "result": result})
                    if is_ajax:
                        return JsonResponse({"ok": True, "bot_messages": [msg], "choices": get_choices_for_step(step)})
                    return redirect("chat")
                answers[qkey] = age_val

            elif "choices" in q:
                ok, val_or_msg = _validate_choice(q, user_msg)
                if not ok:
                    msg = val_or_msg
                    add_bot(messages_sess, msg)
                    request.session.update({"messages": messages_sess, "step": step, "answers": answers, "result": result})
                    if is_ajax:
                        return JsonResponse({"ok": True, "bot_messages": [msg], "choices": get_choices_for_step(step)})
                    return redirect("chat")
                answers[qkey] = val_or_msg

            else:
                answers[qkey] = user_msg

            next_step, next_q = get_next_question(step + 1, answers)

            if next_q:
                step = next_step
                add_bot(messages_sess, next_q["ask"])
                bot_messages.append(next_q["ask"])

                request.session.update({"messages": messages_sess, "step": step, "answers": answers, "result": result})
                if is_ajax:
                    return JsonResponse({
                        "ok": True,
                        "bot_messages": bot_messages,
                        "choices": next_q.get("choices", []) or [],
                    })
                return redirect("chat")

            done_msg = "おすすめを作成中です…（しばらくお待ちください）"
            add_bot(messages_sess, done_msg)
            bot_messages.append(done_msg)

            result = None
            step = 99
            request.session.update({"messages": messages_sess, "step": step, "answers": answers, "result": result})

            if is_ajax:
                return JsonResponse({
                    "ok": True,
                    "bot_messages": bot_messages,
                    "choices": [],
                    "need_rag_progress": True,
                    "init_url": reverse("rag_init"),
                    "progress_url": reverse("rag_progress"),
                    "recommend_url": reverse("rag_recommend"),
                })
            return redirect("chat")

        elif action == "reset":
            for k in ("chat_active", "messages", "step", "answers", "result"):
                if k in request.session:
                    del request.session[k]
            return redirect("chat")

    current_choices = []
    if chat_active and 0 <= step < len(QUESTIONS):
        current_choices = get_choices_for_step(step)

    return render(request, "ijunavi/chat.html", {
        "chat_active": chat_active,
        "messages": messages_sess,
        "step": step,
        "answers": answers,
        "result": result,
        "current_choices": current_choices,
    })


def top(request):
    return render(request, 'ijunavi/top.html')


def chat_history(request):
    messages_sess = request.session.get("messages", [])
    return render(request, 'ijunavi/history.html', {"messages": messages_sess})


def _get_bookmarks(request):
    bms = request.session.get("bookmarks")
    if bms is None:
        bms = []
        request.session["bookmarks"] = bms
    return bms


@login_required
def mypage_view(request):
    return render(request, 'ijunavi/mypage.html', {
        "user": request.user,
    })


@login_required
def profile_edit_view(request):
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
    bookmarks = _get_bookmarks(request)
    return render(request, 'ijunavi/bookmark.html', {
        "bookmarks": bookmarks,
    })


@login_required
def bookmark_remove(request):
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
                place = result["parsed"].get("conclusion_place", "")
                if place:
                    result["headline_display"] = place
                    result["map_address"] = place

                # ★結論からmap_addressを作る（headlineより確実）
                conc = result["parsed"].get("conclusion", "")
                if conc:
                    # 例：「岐阜県岐阜市 ～」から先頭だけ使う
                    conc_head = re.split(r"[、,：:\n]", conc)[0].strip()
                    result["map_address"] = conc_head

        # headline_display が無ければ作る（保険）
        if not result.get("headline_display"):
            result["headline_display"] = format_headline_display(result.get("headline", ""))

        # map_address が無ければ作る（保険）
        if not result.get("map_address"):
            result["map_address"] = result["headline_display"] or extract_address_from_headline(result.get("headline", ""))

        # source_files が無ければ空（保険）
        if "source_files" not in result:
            result["source_files"] = []

    request.session["result"] = result
    request.session["step"] = 100
    request.session.modified = True
    return JsonResponse({"ok": True, "redirect_url": reverse("chat")})
