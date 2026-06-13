const bridge = window.AstrBotPluginPage;

const el = {
  enabled: document.getElementById("enabled"),
  cookie: document.getElementById("cookie"),
  dryRun: document.getElementById("dryRun"),
  todayLogs: document.getElementById("todayLogs"),
  accountLine: document.getElementById("accountLine"),
  drafts: document.getElementById("drafts"),
  tasks: document.getElementById("tasks"),
  logs: document.getElementById("logs"),
  qrBtn: document.getElementById("qrBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  qrBox: document.getElementById("qrBox"),
  qrState: document.getElementById("qrState"),
  qrLink: document.getElementById("qrLink"),
};

let pollTimer = null;
let qrcodeKey = "";

await bridge.ready();
await refresh();

el.refreshBtn.addEventListener("click", refresh);
el.qrBtn.addEventListener("click", createQrCode);

async function refresh() {
  setBusy(el.refreshBtn, true);
  try {
    const data = await bridge.apiGet("dashboard/status");
    el.enabled.textContent = data.enabled ? "启用" : "关闭";
    el.cookie.textContent = data.cookie_configured ? "已配置" : "未配置";
    el.dryRun.textContent = data.dry_run ? "开启" : "关闭";
    el.todayLogs.textContent = String(data.today_logs ?? 0);
    renderAccount(data);
    renderList(el.drafts, data.drafts, renderDraft, "暂无待审核草稿");
    renderList(el.tasks, data.tasks, renderTask, "暂无监听任务");
    renderList(el.logs, data.logs, renderLog, "暂无日志");
  } catch (error) {
    el.accountLine.textContent = messageOf(error);
  } finally {
    setBusy(el.refreshBtn, false);
  }
}

async function createQrCode() {
  stopPolling();
  setBusy(el.qrBtn, true);
  el.qrState.textContent = "正在生成二维码";
  el.qrBox.innerHTML = "<span>生成中</span>";
  try {
    const data = await bridge.apiPost("dashboard/qrcode/create", {});
    if (!data.ok) throw new Error(data.message || "二维码生成失败");
    qrcodeKey = data.qrcode_key;
    const qrImage = data.qr_image || data.qr_svg || "";
    el.qrBox.innerHTML = qrImage
      ? `<img src="${qrImage}" alt="B站扫码登录二维码" />`
      : "<span>二维码渲染失败</span>";
    el.qrLink.href = data.url;
    el.qrState.textContent = "请用 B站客户端扫码";
    pollTimer = window.setInterval(pollQrCode, 2500);
  } catch (error) {
    el.qrBox.innerHTML = "<span>生成失败</span>";
    el.qrLink.removeAttribute("href");
    el.qrState.textContent = messageOf(error);
  } finally {
    setBusy(el.qrBtn, false);
  }
}

async function pollQrCode() {
  if (!qrcodeKey) return;
  try {
    const data = await bridge.apiPost("dashboard/qrcode/poll", { qrcode_key: qrcodeKey });
    if (!data.ok) throw new Error(data.message || "扫码状态获取失败");
    el.qrState.textContent = data.message || data.status;
    if (data.status === "confirmed") {
      stopPolling();
      qrcodeKey = "";
      el.qrBox.innerHTML = "<span>已登录</span>";
      await refresh();
    }
    if (data.status === "expired") {
      stopPolling();
      qrcodeKey = "";
    }
  } catch (error) {
    stopPolling();
    el.qrBox.innerHTML = "<span>轮询失败</span>";
    el.qrState.textContent = messageOf(error);
  }
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = null;
}

function renderAccount(data) {
  if (data.account) {
    el.accountLine.textContent = `${data.account.uname} (${data.account.mid})`;
    return;
  }
  el.accountLine.textContent = data.account_error || "未登录";
}

function renderList(target, rows, renderItem, emptyText) {
  target.innerHTML = "";
  if (!rows || rows.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = emptyText;
    target.append(empty);
    return;
  }
  for (const row of rows) target.append(renderItem(row));
}

function renderDraft(row) {
  return item(
    `${row.draft_id} · ${row.level_label} · rpid=${row.target_rpid}`,
    row.reply_text,
    `root=${row.root} · parent=${row.parent} · ${flags(row.safety_flags)}`
  );
}

function renderTask(row) {
  const state = row.enabled ? "启用" : "暂停";
  return item(`${row.task_id} · ${state} · ${row.mode}`, `${row.bvid} · ${row.title}`, `${row.interval_seconds}s`);
}

function renderLog(row) {
  const state = row.success ? "成功" : "失败";
  return item(`${state} · rpid=${row.target_rpid}`, row.reply_text, row.error_message || timeText(row.created_at));
}

function item(title, body, meta) {
  const node = document.createElement("article");
  node.className = "item";
  node.innerHTML = `
    <div>
      <strong></strong>
      <p></p>
    </div>
    <span></span>
  `;
  node.querySelector("strong").textContent = title;
  node.querySelector("p").textContent = body || "-";
  node.querySelector("span").textContent = meta || "";
  return node;
}

function flags(values) {
  return values && values.length ? values.join(", ") : "无标记";
}

function timeText(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString();
}

function setBusy(button, busy) {
  button.disabled = busy;
  button.dataset.busy = busy ? "1" : "0";
}

function messageOf(error) {
  return error?.message || String(error || "操作失败");
}
