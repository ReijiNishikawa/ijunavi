// static/js/chat.js
(function () {
  const form = document.getElementById("chat-send-form");
  if (!form) return;

  const postUrl = form.dataset.postUrl || window.location.href;

  const USER_NAME = form.dataset.userName || "あなた";
  const BOT_NAME = form.dataset.botName || "いじゅナビ";

  const initUrlDefault = form.dataset.initUrl || "";
  const progressUrlDefault = form.dataset.progressUrl || "";
  const recommendUrlDefault = form.dataset.recommendUrl || "";

  const overlay = document.getElementById("loading-overlay");

  const inputSection = document.getElementById("chat-input");
  const input = form.querySelector('input[name="message"]');

  const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
  const csrf = csrfInput ? csrfInput.value : "";

  const choicesBox = document.getElementById("chat-choices");
  const choicesInner = document.getElementById("chat-choices-inner");

  const progressBar = document.getElementById("ragProgressBar");
  const progressText = document.getElementById("ragProgressText");

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

    const label = role === "bot" ? BOT_NAME : USER_NAME;

    li.innerHTML = `
      <span class="chat-message__role">${label}：</span>
      <span class="chat-message__text chat-pre"></span>
    `;
    li.querySelector(".chat-message__text").textContent = text;

    ul.appendChild(li);

    requestAnimationFrame(() => {
      li.classList.add("is-new");
    });

    li.addEventListener(
      "animationend",
      () => li.classList.remove("is-new"),
      { once: true }
    );

    const logBox = document.querySelector(".chat-log");
    if (logBox) logBox.scrollTop = logBox.scrollHeight;
  }

  function setOverlay(show) {
    if (!overlay) return;
    overlay.style.display = show ? "flex" : "none";
  }

  function setProgress(percent, message) {
    const pct = Math.max(0, Math.min(100, typeof percent === "number" ? percent : 0));
    if (progressBar) progressBar.value = pct;
    if (progressText) progressText.textContent = message || "";
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

  async function sendMessage(text) {
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

    return await res.json();
  }

  function clearChoices() {
    if (!choicesInner) return;
    choicesInner.innerHTML = "";
  }

  function renderChoices(choices) {
    const has = Array.isArray(choices) && choices.length > 0;

    if (has) {
      clearChoices();
      if (choicesBox) choicesBox.style.display = "block";
      if (inputSection) inputSection.style.display = "none";

      choices.forEach((c) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "button login-button";
        btn.textContent = c;

        btn.addEventListener("click", async () => {
          appendMessage("user", c);

          try {
            const data = await sendMessage(c);

            if (!data.ok) {
              appendMessage("bot", "エラーが発生しました。");
              return;
            }

            (data.bot_messages || []).forEach((m, i) => {
              setTimeout(() => {
                appendMessage("bot", m);
              }, 600);
            })
            
            const delay = (data.bot_messages || []).length > 0 ? 600 : 0; 
            setTimeout(() => {
              renderChoices(data.choices || []);
            }, delay);

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
          }
        });

        if (choicesInner) choicesInner.appendChild(btn);
      });
    } else {
      if (choicesBox) choicesBox.style.display = "none";
      if (inputSection) inputSection.style.display = "block";
      clearChoices();
    }
  }

  async function runRagWithProgress(initUrl, progressUrl, recommendUrl) {
    setOverlay(true);
    setProgress(0, "準備中...");

    try {
      const initRes = await postJson(initUrl);
      if (initRes && initRes.state === "error") {
        appendMessage("bot", "エラーが発生しました: " + (initRes.error || ""));
        setOverlay(false);
        return;
      }

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
          setOverlay(false);
          return;
        }

        if (st.state === "error") {
          appendMessage("bot", "エラーが発生しました: " + (st.error || ""));
          setOverlay(false);
          return;
        }

        await new Promise((r) => setTimeout(r, 500));
      }
    } catch (e) {
      appendMessage("bot", "通信エラーが発生しました。");
      setOverlay(false);
    }
  }

  let initialChoices = [];
  try {
    initialChoices = JSON.parse(form.dataset.initialChoices || "[]");
  } catch (e) {
    initialChoices = [];
  }
  renderChoices(initialChoices);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const text = (input.value || "").trim();
    if (!text) return;

    appendMessage("user", text);
    input.value = "";

    try {
      const data = await sendMessage(text);

      if (!data.ok) {
        appendMessage("bot", "エラーが発生しました。");
        return;
      }

      (data.bot_messages || []).forEach((m, i) => {
        setTimeout(() => {
          appendMessage("bot", m);
        }, 600);
      });

      const delay = (data.bot_messages || []).length > 0 ? 600 : 0; 
      setTimeout(() => {
        renderChoices(data.choices || []);
      }, delay);

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
    }
  });
})();