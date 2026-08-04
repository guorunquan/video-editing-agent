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
  const outputList = document.getElementById("output-list");
  const outputDirEl = document.getElementById("output-dir");
  const btnRefresh = document.getElementById("btn-refresh");
  const btnReset = document.getElementById("btn-reset");
  const btnHistory = document.getElementById("btn-history");
  const btnOpenFolder = document.getElementById("btn-open-folder");
  const btnHistoryNew = document.getElementById("btn-history-new");
  const historyModal = document.getElementById("history-modal");
  const historyList = document.getElementById("history-list");
  const sessionNav = document.getElementById("session-nav");

  let busy = false;
  let currentPlayUrl = "";
  let lastUserMessage = "";
  let activeOutputName = "";
  let latestHistory = null;
  let viewingSessionId = "";

  const CHAT_TIMEOUT_MS = 120000;
  const CHAT_WARN_MS = 20000;
  const CHAT_WARN2_MS = 60000;

  function formatDetail(detail) {
    if (!detail) return "请求失败，请重试。";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (typeof item === "string" ? item : item.msg || JSON.stringify(item)))
        .join("；");
    }
    return JSON.stringify(detail);
  }

  function friendlyClientError(err) {
    if (!err) return "未知错误，请重试。";
    if (err.name === "AbortError") {
      return (
        "超过 120 秒仍无响应，已停止等待。\n" +
        "请检查 VPN / HTTPS_PROXY 后点「重试上一条」。"
      );
    }
    const msg = String(err.message || err);
    if (/failed to fetch|networkerror|load failed/i.test(msg)) {
      return "网络异常。请确认 web_app 仍在运行，并检查 VPN。";
    }
    return `网络错误：${msg}`;
  }

  function decorateReply(reply) {
    const text = reply || "(无回复)";
    if (/ConnectTimeout|10060|10061|ConnectError/i.test(text)) {
      return (
        text +
        "\n\n提示：浏览器开 VPN 有时帮不到 Python。请在 .env 设置 HTTPS_PROXY 后重启。"
      );
    }
    return text;
  }

  function looksLikeConfirm(reply, flag) {
    if (flag) return true;
    const text = reply || "";
    return /【待确认】|待确认|请确认|确认后|回复「确认」|回复"确认"|confirmed=true/.test(text);
  }

  function addBubble(text, role = "assistant") {
    if (!messagesEl) return null;
    const div = document.createElement("div");
    div.className = `bubble ${role}`;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function clearConfirmCards() {
    if (!messagesEl) return;
    messagesEl.querySelectorAll(".confirm-card").forEach((el) => el.remove());
  }

  function addConfirmCard(details = null) {
    if (!messagesEl) return null;
    clearConfirmCards();
    const wrap = document.createElement("div");
    wrap.className = "confirm-card";
    const title = escapeHtml(details?.title || "需要你确认才会改文件");
    const summary = escapeHtml(details?.summary || "确认后才会写入 output/，取消不会修改原片。");
    wrap.innerHTML = `
      <p>${title}</p>
      <div class="confirm-summary">${summary.replace(/\n/g, "<br />")}</div>
      <div class="confirm-actions">
        <button type="button" class="btn primary" data-act="confirm">确认执行</button>
        <button type="button" class="btn ghost" data-act="cancel">取消</button>
      </div>
    `;
    wrap.querySelector('[data-act="confirm"]').addEventListener("click", () => {
      wrap.remove();
      sendChat("确认");
    });
    wrap.querySelector('[data-act="cancel"]').addEventListener("click", () => {
      wrap.remove();
      sendChat("取消，不要执行这次计划");
    });
    messagesEl.appendChild(wrap);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return wrap;
  }

  function setBusy(next) {
    busy = next;
    if (sendBtn) sendBtn.disabled = next;
    if (fileInput) fileInput.disabled = next;
    if (btnReset) btnReset.disabled = next;
  }

  function setPlayer(url, force = false, name = "") {
    if (!player || !playerEmpty) return;
    if (!url) {
      player.removeAttribute("src");
      player.load();
      player.classList.remove("is-active");
      playerEmpty.classList.remove("is-hidden");
      currentPlayUrl = "";
      activeOutputName = "";
      highlightOutput();
      return;
    }
    if (!force && url === currentPlayUrl) {
      if (name) activeOutputName = name;
      highlightOutput();
      return;
    }
    currentPlayUrl = url;
    activeOutputName = name || "";
    player.src = url;
    player.load();
    player.classList.add("is-active");
    playerEmpty.classList.add("is-hidden");
    highlightOutput();
  }

  function highlightOutput() {
    if (!outputList) return;
    outputList.querySelectorAll("li[data-name]").forEach((li) => {
      li.classList.toggle("is-active", li.dataset.name === activeOutputName);
    });
  }

  async function renameOutput(oldName) {
    const suggested = oldName.replace(/\.[^.]+$/, "");
    const inputName = window.prompt("新的成片文件名（可省略后缀）：", suggested);
    if (inputName == null) return;
    const newName = inputName.trim();
    if (!newName) return;
    try {
      const res = await fetch("/api/outputs/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: oldName, new_name: newName }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        addBubble(formatDetail(data.detail) || "重命名失败", "system");
        return;
      }
      addBubble(data.message || "已重命名", "system");
      currentPlayUrl = "";
      applyState(data.state);
    } catch (err) {
      addBubble(friendlyClientError(err), "system");
    }
  }

  async function revealOutput(name) {
    try {
      const res = await fetch("/api/outputs/reveal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name || null }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        addBubble(formatDetail(data.detail) || "打开失败", "system");
        return;
      }
      addBubble(data.message || "已打开文件夹", "system");
      if (data.path && navigator.clipboard) {
        try {
          await navigator.clipboard.writeText(data.path);
          addBubble(`路径已复制：${data.path}`, "system");
        } catch {
          /* ignore clipboard failures */
        }
      }
    } catch (err) {
      addBubble(friendlyClientError(err), "system");
    }
  }

  function renderOutputs(outputs) {
    if (!outputList) return;
    outputList.innerHTML = "";
    const list = Array.isArray(outputs) ? outputs : [];
    if (!list.length) {
      const li = document.createElement("li");
      li.className = "empty-hint";
      li.textContent = "暂无导出成片";
      outputList.appendChild(li);
      return;
    }

    for (const item of list) {
      const url = item.url || "";
      const name = item.name || "未命名";
      const li = document.createElement("li");
      li.dataset.name = name;
      if (name === activeOutputName) li.classList.add("is-active");

      const main = document.createElement("div");
      main.className = "out-main";
      main.innerHTML = `<span class="out-name" title="${name}">${name}</span><span class="out-meta">${
        item.size_mb != null ? item.size_mb + " MB" : ""
      }</span>`;
      main.addEventListener("click", () => {
        if (!url) return;
        setPlayer(url, true, name);
        if (mediaMeta) mediaMeta.textContent = `正在播放成片：${name}`;
      });

      const actions = document.createElement("div");
      actions.className = "out-actions";
      actions.innerHTML = `
        <button type="button" class="mini" data-act="rename">改名</button>
        <button type="button" class="mini" data-act="reveal">位置</button>
        <a class="mini mini-link" data-act="download" href="/api/outputs/download/${encodeURIComponent(name)}">下载</a>
      `;
      actions.querySelector('[data-act="rename"]').addEventListener("click", (e) => {
        e.stopPropagation();
        renameOutput(name);
      });
      actions.querySelector('[data-act="reveal"]').addEventListener("click", (e) => {
        e.stopPropagation();
        revealOutput(name);
      });

      li.appendChild(main);
      li.appendChild(actions);
      outputList.appendChild(li);
    }
  }

  function applyState(state, preferUrl) {
    if (!state) return;
    renderOutputs(state.outputs || []);

    if (outputDirEl) {
      outputDirEl.textContent = state.output_dir ? `目录：${state.output_dir}` : "";
      outputDirEl.title = state.output_dir || "";
    }

    const playUrl =
      preferUrl ||
      state.play_url ||
      state.latest_output?.url ||
      state.working_video?.url;

    let playName = "";
    if (state.latest_output && state.latest_output.url === playUrl) {
      playName = state.latest_output.name;
    } else if (preferUrl && state.working_video?.url === preferUrl) {
      playName = state.working_video.name;
    } else if (state.working_video && state.working_video.url === playUrl) {
      playName = state.working_video.name;
    }

    setPlayer(
      playUrl || "",
      Boolean(preferUrl) || Boolean(playUrl && playUrl !== currentPlayUrl),
      playName
    );

    const working = state.working_video;
    const latest = state.latest_output;
    if (mediaMeta) {
      if (working || latest) {
        const parts = [];
        if (working) parts.push(`工作视频：${working.name}`);
        if (latest) parts.push(`最新成片：${latest.name}`);
        mediaMeta.textContent = parts.join(" · ");
      } else {
        mediaMeta.textContent = "尚未选择工作视频";
      }
    }

    if (!previewStrip) return;
    const previews = state.previews || [];
    if (previews.length) {
      previewStrip.hidden = false;
      previewStrip.innerHTML = "";
      for (const item of previews.slice(0, 6)) {
        if (!item.url) continue;
        const card = document.createElement("button");
        card.type = "button";
        card.className = "preview-card";
        const label =
          item.label ||
          (item.at_sec != null ? `第 ${item.at_sec} 秒` : item.name || "截帧");
        card.innerHTML = `<img src="${item.url}" alt="${label}" /><span>${label}</span>`;
        card.title = `${label} · ${item.name || ""}`;
        card.addEventListener("click", () => window.open(item.url, "_blank"));
        previewStrip.appendChild(card);
      }
    } else {
      previewStrip.hidden = true;
      previewStrip.innerHTML = "";
    }
  }

  function formatTime(ts) {
    try {
      return new Date(ts * 1000).toLocaleString();
    } catch {
      return "";
    }
  }

  function formatClock(ts) {
    try {
      return new Date(ts * 1000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return "";
    }
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderHistoryItems(items) {
    if (!historyList) return;
    historyList.innerHTML = "";
    if (!items || !items.length) {
      historyList.innerHTML = `<p class="empty-hint">这个会话还没有消息</p>`;
      return;
    }
    for (const item of items) {
      const row = document.createElement("div");
      row.className = `history-item role-${item.role || "assistant"}`;
      const roleLabel =
        item.role === "user" ? "你" : item.role === "system" ? "系统" : "助手";
      row.innerHTML = `
        <div class="history-meta"><span>${roleLabel}</span><time>${formatTime(item.ts)}</time></div>
        <pre>${escapeHtml(item.text || "")}</pre>
      `;
      historyList.appendChild(row);
    }
    historyList.scrollTop = historyList.scrollHeight;
  }

  function renderSessionNav(history) {
    if (!sessionNav) return;
    sessionNav.innerHTML = "";
    const groups = history.groups || [];
    if (!groups.length) {
      sessionNav.innerHTML = `<p class="empty-hint">暂无会话</p>`;
      return;
    }
    const activeId = viewingSessionId || history.active_id;
    for (const group of groups) {
      const block = document.createElement("div");
      block.className = "session-day";
      block.innerHTML = `<div class="session-day-title">${group.date}</div>`;
      for (const s of group.sessions || []) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "session-item" + (s.id === activeId ? " is-active" : "");
        btn.innerHTML = `
          <span class="session-title">${escapeHtml(s.title || "新对话")}</span>
          <span class="session-sub">${formatClock(s.updated_at)} · ${s.count || 0} 条</span>
        `;
        btn.addEventListener("click", () => selectSession(s.id));
        block.appendChild(btn);
      }
      sessionNav.appendChild(block);
    }
  }

  async function loadHistory(sessionId) {
    const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const res = await fetch(`/api/history${q}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function selectSession(sessionId) {
    viewingSessionId = sessionId;
    try {
      const res = await fetch("/api/history/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        addBubble(formatDetail(data.detail) || "切换会话失败", "system");
        return;
      }
      latestHistory = data.history;
      renderSessionNav(latestHistory);
      renderHistoryItems(latestHistory.items || []);
    } catch (err) {
      addBubble(friendlyClientError(err), "system");
    }
  }

  function openHistory(history) {
    latestHistory = history;
    viewingSessionId = history.active_id || "";
    renderSessionNav(history);
    renderHistoryItems(history.items || []);
    if (!historyModal) {
      addBubble("找不到对话记录面板，请 Ctrl+F5 强制刷新页面。", "system");
      return;
    }
    historyModal.hidden = false;
    historyModal.classList.add("is-open");
    historyModal.setAttribute("aria-hidden", "false");
  }

  function closeHistory() {
    if (!historyModal) return;
    historyModal.hidden = true;
    historyModal.classList.remove("is-open");
    historyModal.setAttribute("aria-hidden", "true");
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
    if (!isRetry) addBubble(message, "user");
    else addBubble(`重试：${message}`, "system");
    if (input) input.value = "";
    const pending = addBubble("思考并调用工具中…", "assistant pending");
    setBusy(true);

    const controller = new AbortController();
    const warnTimer = setTimeout(() => {
      if (pending && pending.isConnected) {
        pending.textContent = "已等待约 20 秒…请确认 VPN / HTTPS_PROXY。";
      }
    }, CHAT_WARN_MS);
    const warn2Timer = setTimeout(() => {
      if (pending && pending.isConnected) {
        pending.textContent = "已等待约 60 秒，仍在等服务端结果…";
      }
    }, CHAT_WARN2_MS);
    const abortTimer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (pending) pending.remove();
      if (!res.ok) {
        addBubble(decorateReply(formatDetail(data.detail)), "assistant");
        return;
      }
      const reply = decorateReply(data.reply || "(无回复)");
      addBubble(reply, "assistant");
      if (looksLikeConfirm(reply, data.needs_confirm)) addConfirmCard(data.confirmation);
      else clearConfirmCards();
      currentPlayUrl = "";
      applyState(data.state);
      if (data.history) latestHistory = data.history;
    } catch (err) {
      if (pending) pending.remove();
      addBubble(friendlyClientError(err), "assistant");
    } finally {
      clearTimeout(warnTimer);
      clearTimeout(warn2Timer);
      clearTimeout(abortTimer);
      setBusy(false);
      if (input) input.focus();
    }
  }

  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      sendChat(input ? input.value : "");
    });
  }

  if (input) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendChat(input.value);
      }
    });
  }

  const chips = document.getElementById("chips");
  if (chips) {
    chips.addEventListener("click", (e) => {
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
  }

  document.querySelectorAll(".quick-action").forEach((button) => {
    button.addEventListener("click", () => sendChat(button.dataset.prompt || ""));
  });

  if (fileInput) {
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
        if (pending) pending.remove();
        if (!res.ok) {
          addBubble(formatDetail(data.detail) || "上传失败", "system");
          return;
        }
        addBubble(data.message || "上传成功", "system");
        currentPlayUrl = "";
        applyState(data.state, data.url);
      } catch (err) {
        if (pending) pending.remove();
        addBubble(friendlyClientError(err), "system");
      } finally {
        setBusy(false);
      }
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener("click", async () => {
      try {
        currentPlayUrl = "";
        await refreshState();
        addBubble("已刷新预览与成片列表", "system");
      } catch (err) {
        addBubble(`刷新失败：${err.message || err}`, "system");
      }
    });
  }

  if (btnOpenFolder) {
    btnOpenFolder.addEventListener("click", () => revealOutput(null));
  }

  if (btnHistory) {
    btnHistory.addEventListener("click", async () => {
      try {
        const history = await loadHistory();
        openHistory(history);
      } catch (err) {
        addBubble(`加载对话记录失败：${err.message || err}`, "system");
      }
    });
  }

  if (btnHistoryNew) {
    btnHistoryNew.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/history/new", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          addBubble(formatDetail(data.detail) || "创建失败", "system");
          return;
        }
        if (messagesEl) messagesEl.innerHTML = "";
        addBubble(data.message || "已开始新对话", "system");
        if (data.history) openHistory(data.history);
      } catch (err) {
        addBubble(friendlyClientError(err), "system");
      }
    });
  }

  if (historyModal) {
    historyModal.addEventListener("click", (e) => {
      if (e.target.closest("[data-close-history]")) closeHistory();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && historyModal && historyModal.classList.contains("is-open")) {
      closeHistory();
    }
  });

  if (btnReset) {
    btnReset.addEventListener("click", async () => {
      if (busy) return;
      setBusy(true);
      try {
        const res = await fetch("/api/reset", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          addBubble(formatDetail(data.detail) || "操作失败", "system");
          return;
        }
        if (messagesEl) messagesEl.innerHTML = "";
        addBubble(data.message || "已开启新对话。", "system");
        currentPlayUrl = "";
        applyState(data.state);
      } catch (err) {
        addBubble(friendlyClientError(err), "system");
      } finally {
        setBusy(false);
      }
    });
  }

  addBubble(
    "欢迎！上传视频后可以问「这个视频怎么剪」，Agent 会根据语音、画面和时间点给建议；修改文件前会先展示计划，确认后才执行。",
    "system"
  );

  refreshState().catch((err) => console.warn("refreshState failed", err));
})();
