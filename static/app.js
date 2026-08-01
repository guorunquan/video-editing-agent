(() => {
  const messagesEl = document.getElementById("messages");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const fileInput = document.getElementById("file-input");
  const player = document.getElementById("player");
  const playerEmpty = document.getElementById("player-empty");
  const mediaMeta = document.getElementById("media-meta");
  const previewStrip = document.getElementById("preview-strip");
  const btnRefresh = document.getElementById("btn-refresh");
  const btnReset = document.getElementById("btn-reset");

  let busy = false;
  let currentPlayUrl = "";
  let lastUserMessage = "";

  // 卡住超时（常见原因：未开 VPN / 连不上 Gemini）
  const CHAT_TIMEOUT_MS = 60000;
  const CHAT_WARN_MS = 20000;

  function formatDetail(detail) {
    if (!detail) return "请求失败";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (typeof item === "string" ? item : item.msg || JSON.stringify(item)))
        .join("；");
    }
    return JSON.stringify(detail);
  }

  function addBubble(text, role = "assistant") {
    const div = document.createElement("div");
    div.className = `bubble ${role}`;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function setBusy(next) {
    busy = next;
    sendBtn.disabled = next;
    fileInput.disabled = next;
    btnReset.disabled = next;
  }

  function setPlayer(url, force = false) {
    if (!url) {
      player.removeAttribute("src");
      player.load();
      player.classList.remove("is-active");
      playerEmpty.classList.remove("is-hidden");
      currentPlayUrl = "";
      return;
    }
    if (!force && url === currentPlayUrl) return;
    currentPlayUrl = url;
    player.src = url;
    player.load();
    player.classList.add("is-active");
    playerEmpty.classList.add("is-hidden");
  }

  function applyState(state, preferUrl) {
    if (!state) return;

    const playUrl =
      preferUrl ||
      state.play_url ||
      state.working_video?.url ||
      state.latest_output?.url;
    setPlayer(playUrl || "", Boolean(preferUrl));

    const working = state.working_video;
    const latest = state.latest_output;
    if (working || latest) {
      const parts = [];
      if (working) parts.push(`工作视频：${working.name}`);
      if (latest) parts.push(`最新成片：${latest.name}`);
      mediaMeta.textContent = parts.join(" · ");
    } else {
      mediaMeta.textContent = "尚未选择工作视频";
    }

    const previews = state.previews || [];
    if (previews.length) {
      previewStrip.hidden = false;
      previewStrip.innerHTML = "";
      for (const item of previews.slice(0, 6)) {
        if (!item.url) continue;
        const img = document.createElement("img");
        img.src = item.url;
        img.alt = item.name;
        img.title = item.name;
        img.addEventListener("click", () => window.open(item.url, "_blank"));
        previewStrip.appendChild(img);
      }
    } else {
      previewStrip.hidden = true;
      previewStrip.innerHTML = "";
    }
  }

  async function refreshState() {
    const res = await fetch("/api/state");
    if (!res.ok) throw new Error(await res.text());
    applyState(await res.json());
  }

  async function sendChat(text, { isRetry = false } = {}) {
    const message = (text || "").trim();
    if (!message || busy) return;

    lastUserMessage = message;
    if (!isRetry) {
      addBubble(message, "user");
    } else {
      addBubble(`重试：${message}`, "system");
    }
    input.value = "";
    const pending = addBubble("思考并调用工具中…", "assistant pending");
    setBusy(true);

    const controller = new AbortController();
    const timeoutSec = Math.round(CHAT_TIMEOUT_MS / 1000);
    const warnSec = Math.round(CHAT_WARN_MS / 1000);
    const warnTimer = setTimeout(() => {
      if (pending.isConnected) {
        pending.textContent =
          `已等待约 ${warnSec} 秒…若未开 VPN，Gemini 可能连不上，可稍后再试。`;
      }
    }, CHAT_WARN_MS);
    const abortTimer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({}));
      pending.remove();
      if (!res.ok) {
        addBubble(formatDetail(data.detail), "assistant");
        return;
      }
      addBubble(data.reply || "(无回复)", "assistant");
      applyState(data.state);
    } catch (err) {
      pending.remove();
      if (err && err.name === "AbortError") {
        addBubble(
          `超过 ${timeoutSec} 秒仍无响应，已停止等待。\n请检查 VPN / 网络后重试（可点下方「重试上一条」）。`,
          "assistant"
        );
      } else {
        addBubble(`网络错误：${err.message || err}\n请检查 VPN / 网络后重试。`, "assistant");
      }
    } finally {
      clearTimeout(warnTimer);
      clearTimeout(abortTimer);
      setBusy(false);
      input.focus();
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    sendChat(input.value);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChat(input.value);
    }
  });

  document.getElementById("chips").addEventListener("click", (e) => {
    const retryBtn = e.target.closest("button[data-retry]");
    if (retryBtn) {
      if (!lastUserMessage) {
        addBubble("还没有可重试的上一条消息。", "system");
        return;
      }
      sendChat(lastUserMessage, { isRetry: true });
      return;
    }
    const btn = e.target.closest("button[data-prompt]");
    if (!btn) return;
    sendChat(btn.dataset.prompt);
  });

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    if (!file || busy) return;

    setBusy(true);
    const pending = addBubble(`正在上传 ${file.name}…`, "system");
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body });
      const data = await res.json().catch(() => ({}));
      pending.remove();
      if (!res.ok) {
        addBubble(formatDetail(data.detail) || "上传失败", "system");
        return;
      }
      addBubble(data.message || "上传成功", "system");
      // 上传后强制切到新片源，不要继续播旧成片
      applyState(data.state, data.url);
    } catch (err) {
      pending.remove();
      addBubble(`上传失败：${err.message || err}`, "system");
    } finally {
      setBusy(false);
    }
  });

  btnRefresh.addEventListener("click", async () => {
    try {
      currentPlayUrl = "";
      await refreshState();
      addBubble("已刷新预览", "system");
    } catch (err) {
      addBubble(`刷新失败：${err.message || err}`, "system");
    }
  });

  btnReset.addEventListener("click", async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch("/api/reset", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        addBubble(data.detail || "清空失败", "system");
        return;
      }
      messagesEl.innerHTML = "";
      addBubble("对话已清空。工作视频与成片仍保留，可继续下指令。", "system");
      applyState(data.state);
    } catch (err) {
      addBubble(`清空失败：${err.message || err}`, "system");
    } finally {
      setBusy(false);
    }
  });

  addBubble(
    "欢迎。先上传视频，然后说「去掉前 3 秒」「加标题：决赛高光」「截第 1 秒看看」。会改文件的操作会先给计划，你再点快捷「确认」或输入确认。更完整的用法见项目里的 USAGE.md。",
    "system"
  );

  refreshState().catch(() => {
    /* 首次无状态也没关系 */
  });
})();
