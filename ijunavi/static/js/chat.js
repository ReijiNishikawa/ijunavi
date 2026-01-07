(function () {
  const form = document.getElementById("chat-send-form");
  if (!form) return;

  const overlay = document.getElementById("loading-overlay");
  const input = form.querySelector('input[name="message"]');
  const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');

  const csrf = csrfInput ? csrfInput.value : "";

  const progressBar = document.getElementById("ragProgressBar");
  const progressText = document.getElementById("ragProgressText");
  const loadingTitle = document.getElementById("loading-title");
  const loadingSub = document.getElementById("loading-sub");

  const postUrl = form.dataset.postUrl || window.location.href;
  const initUrlDefault = form.dataset.initUrl || "";
  const progressUrlDefault = form.dataset.progressUrl || "";
  const recommendUrlDefault = form.dataset.recommendUrl || "";

  function ensureLogUl() {
    const logBox = document.querySelector(".chat-log");
    if (!logBox) return null;

    let ul = logBox.querySelector("ul");
    if (!ul) {
      ul = document.createElement("ul");
      logBox.appendChild(ul);
    }
    return ul;
  }

  function appendMessage(role, text) {
    const ul = ensureLogUl();
    if (!ul) return;

    const li = document.createElement("li");
    li.className = `chat-message chat-message--${role}`;
    li.innerHTML = `<span class="chat-message__role">${role}：</span>
                    <span class="chat-message__text"></span>`;
    li.querySelector(".chat-message__text").textContent = text;
    ul.appendChild(li);

    const logBox = document.querySelector(".chat-log");
    if (logBox) logBox.scrollTop = logBox.scrollHeight;
  }

  async function postJson(url, bodyFormData) {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrf,
        "X-Requested-With": "XMLHttpRequest",
      },
      body: bodyFormData || null,
    });
    return await res.json();
  }

  async function getJson(url) {
    const res = await fetch(url, {
      method: "GET",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    });
    return await res.json();
  }

  function setProgress(percent, message) {
    const pct = Math.max(0, Math.min(100, percent || 0));
    if (progressBar) progressBar.value = pct;
    if (progressText) progressText.textContent = message || "";
  }

  async function runRagWithProgress(initUrl, progressUrl, recommendUrl) {
    if (loadingTitle) loadingTitle.textContent = "おすすめを作成中…";
    if (loadingSub) loadingSub.textContent = "データを検索して回答を生成しています";
    setProgress(0, "準備中...");

    await postJson(initUrl);

    while (true) {
      const st = await getJson(progressUrl);

      const pct = typeof st.percent === "number" ? st.percent : 0;
      const msg = st.message || "";
      setProgress(pct, msg);

      if (st.state === "ready") {
        const r = await postJson(recommendUrl);
        if (r.redirect_url) {
          window.location.href = r.redirect_url;
          return;
        }
        appendMessage("bot", "結果取得に失敗しました。");
        return;
      }

      if (st.state === "error") {
        appendMessage("bot", "エラーが発生しました: " + (st.error || ""));
        return;
      }

      await new Promise((r) => setTimeout(r, 500));
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const text = (input.value || "").trim();
    if (!text) return;

    appendMessage("user", text);
    input.value = "";

    if (overlay) overlay.style.display = "flex";

    try {
      const fd = new FormData();
      fd.append("action", "send");
      fd.append("message", text);

      const res = await fetch(postUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrf,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: fd,
      });

      const data = await res.json();

      if (!data.ok) {
        appendMessage("bot", "エラーが発生しました。");
        return;
      }

      (data.bot_messages || []).forEach((m) => appendMessage("bot", m));

      if (data.need_rag_progress) {
        const initUrl = data.init_url || initUrlDefault;
        const progressUrl = data.progress_url || progressUrlDefault;
        const recommendUrl = data.recommend_url || recommendUrlDefault;

        if (!initUrl || !progressUrl || !recommendUrl) {
          appendMessage("bot", "進捗用URLが設定されていません。");
          return;
        }

        await runRagWithProgress(initUrl, progressUrl, recommendUrl);
        return;
      }

      if (data.redirect_url) {
        window.location.href = data.redirect_url;
        return;
      }
    } catch (err) {
      appendMessage("bot", "通信エラーが発生しました。");
    } finally {
      if (overlay) overlay.style.display = "none";
    }
  });
})();
