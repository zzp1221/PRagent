const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const titles = {
  overview: "运行总览",
  onboard: "接入向导",
  review: "发起审查",
  tasks: "任务中心",
  skills: "Skill 注册中心",
  evolution: "演进实验室",
  guide: "使用说明",
};

const subtitles = {
  overview: "了解审查进展，快速开始下一次代码审查",
  onboard: "三步完成配置，让新提交的 PR 自动得到审查",
  review: "提交代码变更，检查潜在问题并获取修复建议",
  tasks: "查找审查任务，查看问题详情与处理建议",
  skills: "了解每项审查能力的用途与当前配置",
  evolution: "根据审查反馈评测改进方案，查看版本效果",
  guide: "从第一次审查到读懂报告，按步骤说明如何操作",
};

const stateLabels = {
  PENDING: "等待中",
  PLANNING: "规划中",
  EXECUTING: "执行中",
  REVIEWING: "汇总中",
  SUCCESS: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
};

const severityLabels = { critical: "严重", high: "高危", medium: "中危", low: "低危", info: "提示" };
const riskLabels = { none: "无", low: "低", medium: "中", high: "高", critical: "严重", unknown: "未知" };

let selectedTask = null;
let selectedTaskData = null;
let taskCache = [];
let tasksRequest = 0;
let taskDetailRequest = 0;
let modelAvailable = null;
let accessToken = localStorage.getItem("pragent_token") || "";
let toastTimer = null;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value ?? "";
  return node.innerHTML;
}

function formatTime(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      }).format(date);
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

function formatCount(value) {
  const number = Number(value || 0);
  return number >= 1000 ? `${(number / 1000).toFixed(1)}k` : String(number);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("json") ? await response.json() : await response.text();

  if (response.status === 401) {
    $("#login-overlay").classList.remove("hidden");
    $("#logout").classList.add("hidden");
  }
  if (!response.ok) {
    const plainText = typeof data === "string" && !/<[a-z][\s\S]*>/i.test(data) ? data.trim() : "";
    const message = typeof data === "object"
      ? data.error || data.detail
      : plainText || `请求失败 (${response.status})`;
    throw new Error(message || response.statusText || "请求失败");
  }
  return data;
}

function toast(message, duration = 2600) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), duration);
}

function setButtonBusy(button, busy, busyText) {
  if (!button) return;
  button.setAttribute("aria-busy", String(busy));
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.disabled = true;
    button.textContent = busyText;
  } else {
    button.disabled = false;
    if (button.dataset.label) button.innerHTML = button.dataset.label;
  }
}

function show(view, updateHash = true) {
  if (!titles[view]) {
    view = "overview";
    history.replaceState(null, "", "#overview");
  }
  $$(".view").forEach((element) => element.classList.remove("active"));
  $$(".nav-item").forEach((element) => {
    const active = element.dataset.view === view;
    element.classList.toggle("active", active);
    element.setAttribute("aria-current", active ? "page" : "false");
  });
  $(`#view-${view}`).classList.add("active");
  $("#page-title").textContent = titles[view];
  $("#page-sub").textContent = subtitles[view] || "";
  document.title = `${titles[view]} · PRAgent`;
  if (updateHash) history.replaceState(null, "", `#${view}`);

  if (view === "overview") loadDashboard();
  if (view === "onboard") loadOnboarding();
  if (view === "tasks") loadTasks();
  if (view === "skills") loadSkills();
  if (view === "evolution") loadFailures();
  if (view === "guide") loadGuide();
  window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
}

$$(".nav-item").forEach((button) => button.addEventListener("click", () => show(button.dataset.view)));
$$("[data-jump]").forEach((button) => button.addEventListener("click", () => show(button.dataset.jump)));
window.addEventListener("hashchange", () => show(location.hash.slice(1), false));

function syncSelection() {
  if (!selectedTask) return;
  $$(".task-row[data-task]").forEach((row) => {
    const selected = row.dataset.task === selectedTask;
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-pressed", String(selected));
  });
}

function taskRows(tasks) {
  if (!tasks?.length) {
    return '<div class="empty-state"><span><b>还没有审查任务</b>提交一个 diff 开始首次审查。</span></div>';
  }
  return tasks.map((task) => {
    const state = String(task.state || "PENDING").toUpperCase();
    const repository = escapeHtml(task.repository || "未命名仓库");
    const pr = task.pull_request ? `PR #${escapeHtml(task.pull_request)}` : "手动审查";
    const selected = selectedTask && task.id === selectedTask ? " is-selected" : "";
    return `
      <button class="task-row${selected}" data-task="${escapeHtml(task.id)}" type="button">
        <span class="task-main">
          <span class="task-glyph">PR</span>
          <span class="task-copy">
            <span class="task-name">${repository}</span>
            <span class="task-meta"><span>${pr}</span><span>${escapeHtml(formatTime(task.created_at))}</span></span>
          </span>
        </span>
        <span class="status state-${state.toLowerCase()}">${stateLabels[state] || escapeHtml(state)}</span>
      </button>`;
  }).join("");
}

function bindTasks(root) {
  $$("[data-task]", root).forEach((row) => row.addEventListener("click", () => openTask(row.dataset.task)));
  syncSelection();
}

function statCard(label, value, note, style, icon) {
  return `<article class="stat ${style}">
    <div class="stat-head"><span>${label}</span><i>${icon}</i></div>
    <b>${value}</b><small>${note}</small>
  </article>`;
}

function renderLlmRuntime(llm = {}, runMode = {}) {
  const enabled = Boolean(llm.enabled);
  const failed = Boolean(llm.error);
  modelAvailable = failed ? null : enabled;
  const provider = String(llm.provider || "local");
  const model = String(llm.model || "");
  const detail = failed
    ? "暂时无法读取模型配置"
    : enabled
      ? `${provider} / ${model || "默认模型"}，参与上下文审查与风险判断`
      : "未配置模型；agentic 审查暂不可用";
  const state = failed ? "读取失败" : enabled ? "已启用" : "待配置";
  const runtime = failed
    ? "运行时状态未知"
    : enabled
      ? `${provider} / ${model || "模型已配置"}`
      : "agentic / 需要模型配置";

  const chain = $("#execution-chain");
  if (chain) {
    const scanner = '<div class="agent-step"><b>01</b><span><strong>收集代码信息</strong><small>扫描规则、代码结构与相关上下文</small></span><em class="done">扫描</em></div>';
    const gate = '<i class="flow-line"></i><div class="agent-step"><b>03</b><span><strong>验证审查结论</strong><small>校验证据、置信度与发布条件</small></span><em class="done">验证</em></div>';
    const llmStep = `<i class="flow-line"></i><div class="agent-step is-active" id="llm-agent-step"><b>02</b><span><strong>多角色协作审查</strong><small id="llm-agent-detail">${escapeHtml(detail)}</small></span><em id="llm-agent-state">${escapeHtml(state)}</em></div>`;
    chain.innerHTML = scanner + llmStep + gate;
  }

  const step = $("#llm-agent-step");
  if (step) {
    step.classList.remove("is-pending");
    step.classList.toggle("is-active", enabled);
    step.classList.toggle("is-disabled", !enabled && !failed);
    step.classList.toggle("is-error", failed);
    const detailNode = $("#llm-agent-detail");
    const stateNode = $("#llm-agent-state");
    if (detailNode) detailNode.textContent = detail;
    if (stateNode) stateNode.textContent = state;
  }

  const status = $("#llm-runtime-status");
  status.className = `runtime-status ${failed ? "is-error" : enabled ? "is-active" : "is-disabled"}`;
  status.textContent = state;
  const capability = $("#llm-capability");
  capability.classList.toggle("is-active", enabled);
  capability.classList.toggle("is-disabled", !enabled && !failed);
  capability.classList.toggle("is-error", failed);
  $("#llm-capability-detail").textContent = detail;
  $("#llm-runtime-model").textContent = runtime;
  const badge = $("#runtime-badge");
  if (badge) {
    badge.className = `status ${failed ? "state-failed" : enabled ? "status-online" : "state-pending"}`;
    badge.textContent = failed ? "模型状态未知" : enabled ? "模型已就绪" : "需要配置模型";
  }
}

async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    renderLlmRuntime(data.llm, data.run_mode);
    const modeSelect = $("#review-mode");
    if (modeSelect) {
      modeSelect.value = "agentic";
      modeSelect.disabled = !data.llm?.enabled;
    }
    $("#system-status").textContent = "服务已连接";
    $("#system-status").dataset.connected = "true";
    $("#system-status").title = `${data.queue} · ${data.orchestrator}`;
    const stats = data.stats || {};
    const rate = Math.round(Number(stats.success_rate || 0) * 100);
    $("#stats").innerHTML = [
      statCard("总任务", stats.tasks_total ?? 0, "累计审查任务", "", "ALL"),
      statCard("已完成", stats.tasks_success ?? 0, "已生成审查报告", "success", "OK"),
      statCard("失败", stats.tasks_failed ?? 0, "需要进一步处理", "failed", "ERR"),
      statCard("成功率", `${rate}%`, "全部任务成功率", "rate", "RATE"),
    ].join("");
    if ($("#overview-feedback")) $("#overview-feedback").textContent = stats.unresolved_failure_cases ?? 0;
    if ($("#overview-skills")) $("#overview-skills").textContent = stats.active_skill_versions ?? 0;
    $("#recent-tasks").innerHTML = taskRows((data.tasks || []).slice(0, 5));
    bindTasks($("#recent-tasks"));
  } catch (error) {
    renderLlmRuntime({ error: true }, {});
    $("#system-status").textContent = "服务连接异常";
    $("#system-status").dataset.connected = "false";
    $("#system-status").title = error.message;
    if ($("#overview-feedback")) $("#overview-feedback").textContent = "待连接";
    if ($("#overview-skills")) $("#overview-skills").textContent = "待连接";
    $("#stats").innerHTML = '<div class="empty-state"><span><b>暂时无法读取数据</b>请检查服务状态后重试。</span></div>';
    $("#recent-tasks").innerHTML = '<div class="empty-state"><span>数据加载失败</span></div>';
    toast(error.message);
  }
}

function renderTaskList() {
  const root = $("#all-tasks");
  const query = ($("#task-search")?.value || "").trim().toLowerCase();
  const filter = $("#task-filter")?.value || "all";
  const tasks = taskCache.filter((task) => {
    const state = String(task.state || "PENDING").toUpperCase();
    const matchesState = filter === "all" || (filter === "active" ? ACTIVE_STATES.has(state) : state === filter);
    const text = [task.repository, task.pull_request, task.id].filter((value) => value != null).join(" ").toLowerCase();
    return matchesState && (!query || text.includes(query));
  });
  if ($("#task-count")) $("#task-count").textContent = query || filter !== "all" ? `${tasks.length} / ${taskCache.length} 项` : `${taskCache.length} 项`;
  root.innerHTML = !tasks.length && taskCache.length
    ? '<div class="empty-state"><span><b>没有匹配的任务</b>试试其他仓库、PR 编号或任务状态。</span></div>'
    : taskRows(tasks);
  bindTasks(root);
}

$("#task-search")?.addEventListener("input", renderTaskList);
$("#task-filter")?.addEventListener("change", renderTaskList);
$("#task-back")?.addEventListener("click", () => {
  $("#view-tasks").classList.remove("is-detail");
  $("#task-search")?.focus();
  window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
});

async function loadTasks() {
  const request = ++tasksRequest;
  const root = $("#all-tasks");
  if (!taskCache.length) root.innerHTML = '<div class="list-loading"></div><div class="list-loading"></div>';
  try {
    const data = await api("/api/tasks");
    if (request !== tasksRequest) return;
    taskCache = data.tasks || [];
    renderTaskList();
  } catch (error) {
    if (request !== tasksRequest) return;
    root.innerHTML = '<div class="empty-state"><span>任务加载失败</span></div>';
    if ($("#task-count")) $("#task-count").textContent = "加载失败";
    toast(error.message);
  }
}

const severityOrder = ["critical", "high", "medium", "low", "info"];

const stopReasonLabels = {
  "single-pass": "单步完成",
  "high-risk-single-pass": "高风险单轮",
  "high-risk-one-revision-round": "高风险一轮返工",
};

function renderGateFacts(gate) {
  if (!gate || typeof gate !== "object") return "";
  const unverified = Number(gate.unverified_evidence_count || 0);
  const reasons = Array.isArray(gate.reasons) ? gate.reasons : [];
  const verdict = gate.passed === false
    ? `<span class="is-alert">门禁结论 <b>${reasons.length ? `${reasons.length} 项拦截` : "未通过"}</b></span>`
    : `<span>门禁结论 <b>通过</b></span>`;
  return `<div class="gate-facts">
    <span>位置证据 <b>${gate.exact_location_evidence ? "命中" : "未命中"}</b></span>
    <span>强证据 <b>${Number(gate.strong_evidence_count || 0)}</b></span>
    <span>已验证引用 <b>${Number(gate.verified_evidence_count || 0)}</b></span>
    <span class="${unverified > 0 ? "is-alert" : ""}">未验证引用 <b>${unverified}</b></span>
    ${verdict}
  </div>`;
}

function findingCard(item, index) {
  const severity = String(item.severity || "medium").toLowerCase();
  const location = `${item.path || "未知文件"}:${item.line ?? "?"}`;
  const evidence = String(item.evidence || "").trim();
  const refs = (item.evidence_refs || [])
    .map((ref) => ref?.evidence_id)
    .filter(Boolean);
  const reasons = (item.gate && item.gate.reasons) || [];
  const blocks = [
    renderGateFacts(item.gate),
    evidence ? `<pre>${escapeHtml(evidence)}</pre>` : "",
    item.fix ? `<p><b>建议修复</b> ${escapeHtml(item.fix)}</p>` : "",
    item.test ? `<p><b>建议测试</b> ${escapeHtml(item.test)}</p>` : "",
    refs.length ? `<p><b>证据引用</b> ${escapeHtml(refs.join(", "))}</p>` : "",
    reasons.length ? `<p><b>门禁提示</b> ${escapeHtml(reasons.join("；"))}</p>` : "",
  ].filter(Boolean).join("");

  return `<article class="finding sev-${escapeHtml(severity)}">
    <div class="finding-head">
      <span class="sev-tag">${escapeHtml(severityLabels[severity] || severity)}</span>
      <span class="finding-loc">${escapeHtml(location)}</span>
      ${item.rule_id ? `<span class="finding-rule">${escapeHtml(item.rule_id)}</span>` : ""}
    </div>
    <h4 class="finding-title">${escapeHtml(item.title || `发现 ${index + 1}`)}</h4>
    ${item.explanation ? `<p class="finding-body">${escapeHtml(item.explanation)}</p>` : ""}
    ${blocks ? `<details class="finding-more"><summary>证据与修复建议</summary>${blocks}</details>` : ""}
  </article>`;
}

function renderFindings(findings) {
  if (!findings.length) {
    return '<div class="empty-state"><span><b>未发现需要处理的问题</b>新增代码行通过了当前质量门禁。</span></div>';
  }
  const groups = new Map();
  findings.forEach((item, index) => {
    const severity = String(item.severity || "medium").toLowerCase();
    if (!groups.has(severity)) groups.set(severity, []);
    groups.get(severity).push({ item, index });
  });
  const ordered = [
    ...severityOrder.filter((severity) => groups.has(severity)),
    ...[...groups.keys()].filter((severity) => !severityOrder.includes(severity)),
  ];
  return ordered.map((severity) => `
    <div class="sev-group sev-${escapeHtml(severity)}">
      <div class="sev-group-head">
        <i></i><span>${escapeHtml(severityLabels[severity] || severity)}</span>
        <span class="sev-count">${groups.get(severity).length}</span>
      </div>
      ${groups.get(severity).map((entry) => findingCard(entry.item, entry.index)).join("")}
    </div>`).join("");
}

function renderBudget(budget) {
  if (!budget || typeof budget !== "object") return "";
  const tokenTotal = Number(budget.token_budget || 0);
  const tokensUsed = Number(budget.tokens_used || 0);
  const timeTotal = Number(budget.time_budget_seconds || 0);
  const elapsed = Number(budget.elapsed_seconds || 0);
  const callsTotal = Number(budget.max_model_calls || 0);
  const callsUsed = Number(budget.model_calls || 0);
  const exhausted = String(budget.exhausted || "").trim();

  const row = (label, used, total, format) => {
    if (!total && !used) return "";
    const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
    const tone = total > 0 && pct >= 100 ? " is-full" : pct >= 75 ? " is-hot" : "";
    const text = total > 0 ? `${format(used)} / ${format(total)}` : `${format(used)} / 未设上限`;
    return `<div class="budget-row${tone}">
      <span>${label}</span>
      <div class="budget-track"><div class="budget-fill" style="width:${pct.toFixed(1)}%"></div></div>
      <span class="budget-meta">${text}</span>
    </div>`;
  };

  return `<div class="budget${exhausted ? " is-exhausted" : ""}">
    <div class="budget-head">
      <span>审查预算</span>
      ${exhausted
        ? `<span class="budget-alert">已耗尽 · ${escapeHtml(exhausted)}</span>`
        : '<span>未超预算</span>'}
    </div>
    ${row("Tokens", tokensUsed, tokenTotal, (value) => formatCount(value))}
    ${row("耗时", elapsed, timeTotal, (value) => `${Number(value).toFixed(1)}s`)}
    ${row("模型调用", callsUsed, callsTotal, (value) => String(Math.round(value)))}
  </div>`;
}

function renderGateSummary(gates, rejected) {
  if (!gates || !Object.keys(gates).length) return "";
  const cells = [
    ["格式门禁", gates.format?.rejected],
    ["证据门禁", gates.evidence?.rejected],
    ["置信度门禁", gates.confidence?.rejected],
    ["发布门禁", gates.release?.rejected],
  ];
  const cellHtml = cells.map(([label, count]) => {
    const value = Number(count || 0);
    return `<div class="gate-cell ${value > 0 ? "has-reject" : "is-clean"}">
      <small>${label}</small><b>${value} 拦截</b>
    </div>`;
  }).join("");

  const unverifiedRefs = Number(gates.evidence?.unverified_refs || 0);
  const minimum = gates.confidence?.minimum;
  const rejectedHtml = rejected.length ? `
    <div class="rejected-list">
      ${rejected.slice(0, 5).map((item) => `
        <div class="rejected-item">
          <div class="rejected-head">
            <b>${escapeHtml(item.rule_id || "未命名规则")}</b>
            <span>${escapeHtml(`${item.path || "未知文件"}:${item.line ?? "?"}`)}</span>
          </div>
          <ul>${(item.reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
        </div>`).join("")}
      ${rejected.length > 5 ? `<p class="feedback-empty">另有 ${rejected.length - 5} 条被拦截的结论未显示。</p>` : ""}
    </div>` : "";

  return `<div class="gate-panel">
    <div class="sev-group-head">
      <i style="background:var(--accent)"></i><span>质量门禁</span>
      <span class="sev-count">放行 ${Number(gates.accepted || 0)} · 拦截 ${Number(gates.rejected || 0)}</span>
    </div>
    <div class="gate-grid">${cellHtml}</div>
    <div class="gate-foot">
      ${minimum !== undefined ? `<span>置信度门槛 <b>${Number(minimum).toFixed(2)}</b></span>` : ""}
      <span>未验证证据引用 <b>${unverifiedRefs}</b></span>
    </div>
    ${rejectedHtml}
  </div>`;
}

function summarizeMessage(content) {
  if (content == null) return "";
  if (typeof content === "string") return content.slice(0, 220);
  if (typeof content !== "object") return String(content);
  for (const key of ["note", "reason", "summary", "message", "decision", "status"]) {
    if (content[key]) return String(content[key]).slice(0, 220);
  }
  const keys = Object.keys(content);
  if (!keys.length) return "";
  return keys.slice(0, 4).map((key) => {
    const value = content[key];
    return `${key}=${typeof value === "object" ? "…" : String(value)}`;
  }).join(" · ").slice(0, 220);
}

function renderCollaboration(task) {
  const report = task?.report || {};
  const collab = report.collaboration || {};
  const trace = Array.isArray(task.trace) ? task.trace : [];
  const messages = Array.isArray(task.collaboration) ? task.collaboration : [];
  const roles = Array.isArray(collab.roles) ? collab.roles : [];
  if (!trace.length && !messages.length && !roles.length) return "";

  const items = [
    ...trace.map((item) => ({
      at: item.created_at || "",
      kind: "state",
      role: "harness",
      tag: "状态",
      body: [item.state, item.message].filter(Boolean).join(" · "),
    })),
    ...messages.map((item) => ({
      at: item.created_at || "",
      kind: "message",
      role: `${item.sender || "?"} → ${item.recipient || "?"}`,
      tag: item.kind || "message",
      body: summarizeMessage(item.content),
    })),
  ].sort((left, right) => String(left.at).localeCompare(String(right.at))).slice(0, 14);

  const timeline = items.map((item) => `
    <li class="timeline-item is-${item.kind}">
      <div class="timeline-head">
        <span class="timeline-role">${escapeHtml(item.role)}</span>
        <span class="timeline-kind">${escapeHtml(item.tag)}</span>
        <span class="timeline-time">${escapeHtml(formatTime(item.at))}</span>
      </div>
      ${item.body ? `<p class="timeline-body">${escapeHtml(item.body)}</p>` : ""}
    </li>`).join("");

  return `<details class="collab">
    <summary class="sev-group-head">
      <i style="background:var(--accent)"></i><span>协作过程</span>
      <span class="sev-count">${items.length} 个事件</span>
    </summary>
    ${roles.length ? `<div class="collab-roles">${roles.map((role) => `<span class="collab-role">${escapeHtml(role)}</span>`).join("")}</div>` : ""}
    ${collab.stop_reason ? `<p class="collab-stop">终止原因 <b>${escapeHtml(stopReasonLabels[collab.stop_reason] || collab.stop_reason)}</b></p>` : ""}
    <ul class="timeline">${timeline}</ul>
  </details>`;
}

function renderTaskReport(task) {
  const root = $("#task-report");
  const raw = $("#task-raw-json");
  if (raw) raw.textContent = formatJson(task);

  const report = task?.report;
  if (!report) {
    const state = String(task?.state || "").toUpperCase();
    const stateLabel = stateLabels[state] || task?.state || "未知";
    const error = task?.error;
    const errorMessage = typeof error === "string" ? error : error?.message || error?.detail || (error ? formatJson(error) : "");
    const detail = state === "FAILED" ? "本次审查未完成，可检查失败原因后恢复任务。" : state === "CANCELLED" ? "该任务已取消，需要继续时可以恢复任务。" : "任务完成后会在这里显示审查结论与修复建议。";
    root.innerHTML = `<div class="submission-state">
      <span class="status state-${escapeHtml(state.toLowerCase())}">${escapeHtml(stateLabel)}</span>
      <h3>${state === "FAILED" ? "审查未能完成" : state === "CANCELLED" ? "任务已取消" : "审查正在进行"}</h3>
      <p>${detail}</p>
      ${errorMessage ? `<p class="inline-error" role="alert">${escapeHtml(errorMessage)}</p>` : ""}
    </div>`;
    return;
  }

  const findings = report.findings || [];
  const execution = report.execution || {};
  const budget = execution.review_budget || null;
  const gates = execution.gates || null;
  const rejected = Array.isArray(execution.rejected_findings) ? execution.rejected_findings : [];
  const context = execution.context_management || {};
  const risk = String(report.risk || "unknown").toLowerCase();
  const state = stateLabels[String(task.state || "").toUpperCase()] || task.state || "未知";

  const chips = [
    `<span class="report-chip">${report.pull_request ? `PR #${escapeHtml(report.pull_request)}` : "手动审查"}</span>`,
    `<span class="report-chip risk-${escapeHtml(risk)}">风险 ${escapeHtml(riskLabels[risk] || risk)}</span>`,
    report.reviewer ? `<span class="report-chip">${escapeHtml(report.reviewer)}</span>` : "",
    `<span class="report-chip">${escapeHtml(state)}</span>`,
  ].filter(Boolean).join("");

  const metrics = [];
  if (Object.keys(execution).length) {
    metrics.push(["模型调用", escapeHtml(execution.llm_calls ?? 0)]);
    metrics.push(["工具调用", escapeHtml(execution.tool_calls ?? 0)]);
    if (!budget && execution.total_tokens) metrics.push(["Tokens", formatCount(execution.total_tokens)]);
    if (execution.cost_usd) metrics.push(["成本", `$${Number(execution.cost_usd).toFixed(6)}`]);
    if (!budget && execution.duration_ms) metrics.push(["耗时", `${Math.round(Number(execution.duration_ms))} ms`]);
    if (context.compression_calls) metrics.push(["上下文压缩", `${context.compression_calls} 次`]);
    const recalled = (context.memory_recall || {}).recalled;
    if (recalled) metrics.push(["记忆召回", String(recalled)]);
  }

  root.innerHTML = `
    <div class="report-head">
      <span class="report-repo">${escapeHtml(report.repository || task.repository || "未命名仓库")}</span>
      ${chips}
    </div>
    ${report.summary ? `<p class="report-summary">${escapeHtml(report.summary)}</p>` : ""}
    <div class="findings">
      <div class="findings-label"><span>审查结论</span><span>${findings.length} 项</span></div>
      ${renderFindings(findings)}
    </div>
    ${budget || metrics.length || gates ? `<details class="report-details">
      <summary>执行与质量详情</summary>
      ${renderBudget(budget)}
      ${metrics.length ? `<ul class="report-metrics">${metrics.map(([label, value]) => `<li><small>${label}</small><b>${value}</b></li>`).join("")}</ul>` : ""}
      ${renderGateSummary(gates, rejected)}
    </details>` : ""}
    ${renderCollaboration(task)}`;
}

const ACTIVE_STATES = new Set(["PENDING", "PLANNING", "EXECUTING", "REVIEWING"]);
const RESUMABLE_STATES = new Set(["FAILED", "CANCELLED"]);

function setTaskActions(task) {
  const state = String(task?.state || "").toUpperCase();
  const hasReport = Boolean(task?.report);
  $("#task-cancel").classList.toggle("hidden", !ACTIVE_STATES.has(state));
  $("#task-resume").classList.toggle("hidden", !RESUMABLE_STATES.has(state));
  $("#copy-report").classList.toggle("hidden", !hasReport);
  $("#create-fix").classList.toggle("hidden", !(hasReport && task?.pull_request));
}

async function openTask(id) {
  const request = ++taskDetailRequest;
  const switchingTask = selectedTask !== id;
  if (!$("#view-tasks").classList.contains("active")) show("tasks");
  selectedTask = id;
  selectedTaskData = null;
  $("#view-tasks").classList.add("is-detail");
  syncSelection();
  if ($("#task-selection-label")) $("#task-selection-label").textContent = "正在读取任务详情";
  $("#feedback-panel").classList.add("hidden");
  if (switchingTask) {
    $("#feedback-panel").open = false;
    $("#feedback-form").reset();
    $("#feedback-missed-fields").classList.add("hidden");
    $("#feedback-hint").textContent = "提交后可在本任务和演进实验室查看状态。";
  }
  const raw = $("#task-raw");
  if (raw) raw.open = false;
  $("#task-raw-json").textContent = "";
  setTaskActions({});
  $("#task-report").innerHTML = '<div class="empty-state"><span>正在加载任务报告…</span></div>';
  try {
    const task = await api(`/v1/tasks/${encodeURIComponent(id)}`);
    if (request !== taskDetailRequest || selectedTask !== id) return;
    selectedTaskData = task;
    if ($("#task-selection-label")) $("#task-selection-label").textContent = `${task.repository || "未命名仓库"}${task.pull_request ? ` · PR #${task.pull_request}` : " · 手动审查"}`;
    renderTaskReport(task);
    syncSelection();
    setTaskActions(task);
    const feedbackReady = task.state === "SUCCESS" && task.report;
    $("#feedback-panel").classList.toggle("hidden", !feedbackReady);
    if (feedbackReady) {
      populateFeedbackFindings(task.report.findings || []);
      await loadTaskFeedback(id);
    }
  } catch (error) {
    if (request !== taskDetailRequest || selectedTask !== id) return;
    $("#task-report").innerHTML = `<div class="empty-state"><span><b>报告加载失败</b>${escapeHtml(error.message)}</span></div>`;
    if ($("#task-selection-label")) $("#task-selection-label").textContent = "暂时无法读取此任务";
    selectedTaskData = null;
  }
}

const feedbackLabels = {
  false_positive: "误报",
  missed_issue: "漏报",
  bad_fix: "坏修复",
  accepted: "已接受",
};

function populateFeedbackFindings(findings) {
  const select = $("#feedback-finding");
  const previousValue = select.value;
  select.innerHTML = '<option value="">不关联已有结论</option>' + findings.map((finding, index) => {
    const identity = `${finding.rule_id || "未命名规则"} · ${finding.path || "未知文件"}:${finding.line || "?"}`;
    return `<option value="${index}">${escapeHtml(identity)}</option>`;
  }).join("");
  if (previousValue !== "" && findings[Number(previousValue)]) select.value = previousValue;
  $("#feedback-result").textContent = "";
}

function renderTaskFeedback(cases) {
  const root = $("#task-feedback-history");
  if (!cases.length) {
    root.innerHTML = '<p class="feedback-empty">尚无反馈。提交后，它会在这里保留并进入后续评测。</p>';
    return;
  }
  root.innerHTML = `<p class="list-section-label">本任务反馈</p>${cases.map((item) => {
    const payload = item.payload || {};
    const finding = payload.finding || {};
    const reference = finding.rule_id
      ? `${finding.rule_id}${finding.path ? ` · ${finding.path}:${finding.line || "?"}` : ""}`
      : "未关联审查结论";
    return `<div class="feedback-case">
      <span class="feedback-case-type">${escapeHtml(feedbackLabels[item.category] || item.category)}</span>
      <span class="feedback-case-copy"><b>${escapeHtml(reference)}</b><small>${escapeHtml(payload.note || "未填写说明")}</small></span>
      <span class="status ${item.resolved ? "state-success" : "state-pending"}">${item.resolved ? "已解决" : "待评测"}</span>
    </div>`;
  }).join("")}`;
}

async function loadTaskFeedback(taskId) {
  const root = $("#task-feedback-history");
  root.innerHTML = '<p class="feedback-empty">正在读取本任务反馈…</p>';
  try {
    const data = await api(`/v1/tasks/${encodeURIComponent(taskId)}/feedback`);
    if (selectedTask === taskId) renderTaskFeedback(data.cases || []);
  } catch (error) {
    if (selectedTask === taskId) root.innerHTML = `<p class="feedback-empty">反馈历史读取失败：${escapeHtml(error.message)}</p>`;
  }
}

const skillDescriptions = {
  "api-compatibility": ["接口兼容性", "检查接口、配置和数据结构变更，识别对现有调用方的影响。"],
  "code-quality": ["代码完整性", "检查新增生产代码中的待办标记与尚未完成的实现。"],
  "correctness-review": ["逻辑正确性", "检查边界条件、数据处理与业务逻辑中的缺陷。"],
  "database-review": ["数据库变更", "检查查询、事务与数据迁移可能造成的数据问题。"],
  "observability-review": ["运行可观测性", "检查日志、指标与追踪，帮助定位线上故障。"],
  "performance-review": ["性能检查", "检查重复计算、资源开销与潜在性能瓶颈。"],
  "reliability-review": ["稳定性检查", "检查异常处理、重试、并发与故障恢复逻辑。"],
  "security-review": ["安全检查", "检查输入校验、权限控制与敏感信息等安全问题。"],
  "test-quality": ["测试质量", "检查测试是否覆盖关键行为、边界条件与失败场景。"],
};

async function loadSkills() {
  const root = $("#skill-list");
  root.innerHTML = '<div class="skill-card loading"></div><div class="skill-card loading"></div>';
  try {
    const data = await api("/api/skills");
    renderLlmRuntime(data.llm);
    const skills = (data.skills || []).filter((skill) => skill.name !== "llm-review");
    root.innerHTML = skills.length ? skills.map((skill) => {
      const copy = skillDescriptions[skill.name];
      return `
      <article class="skill-card">
        <span class="skill-label">${skill.sandboxed ? "独立沙箱运行" : "已加载能力"}</span>
        <h3>${escapeHtml(copy?.[0] || skill.name)}</h3>
        <p>${escapeHtml(copy?.[1] || skill.description || "暂无能力描述")}</p>
        <details class="skill-details"><summary>能力信息</summary>
          <span class="skill-meta">${escapeHtml(skill.name)} · v${escapeHtml(skill.version || "1")}</span>
          <span class="skill-meta">来源：${escapeHtml(skill.source || "未提供")}</span>
          ${copy && skill.description ? `<p>${escapeHtml(skill.description)}</p>` : ""}
        </details>
      </article>`;
    }).join("") : '<div class="empty-state"><span><b>尚未加载 Skill</b>扫描目录以加载可用能力。</span></div>';
  } catch (error) {
    renderLlmRuntime({ error: true });
    root.innerHTML = '<div class="empty-state"><span>Skills 加载失败</span></div>';
    toast(error.message);
  }
}

const evolutionDecisions = {
  activated: "已激活新版本",
  shadow_ready: "已通过评测，等待灰度验证",
  rejected: "候选未通过评测",
  deferred: "候选已保存，等待评测条件",
};

function renderEvolutionStatus(status) {
  $("#evolution-status").textContent = formatJson(status);
  const root = $("#evolution-summary");
  if (!root) return;
  const checks = [
    ["审查模型", Boolean(status.model_configured), status.model_configured ? `${status.provider || "已配置"}${status.model ? ` / ${status.model}` : ""}` : "尚未配置模型"],
    ["验证案例", Number(status.validation_cases || 0) >= Number(status.minimum_cases || 0), `${status.validation_cases ?? 0} / 至少 ${status.minimum_cases ?? 0} 例`],
    ["独立测试集", Number(status.holdout_cases || 0) >= Number(status.minimum_holdout_cases || 0), `${status.holdout_cases ?? 0} / 至少 ${status.minimum_holdout_cases ?? 0} 例`],
  ];
  root.innerHTML = checks.map(([label, ready, detail]) => `<div class="evolution-summary-item">
    <span>${label}</span><b class="${ready ? "is-ready" : "is-pending"}">${ready ? "已就绪" : "待准备"}</b><small>${escapeHtml(detail)}</small>
  </div>`).join("");
  const badge = $("#evolution-ready");
  if (badge) {
    badge.textContent = status.ready ? "可以开始评测" : "尚未满足评测条件";
    badge.className = `status ${status.ready ? "status-online" : "state-pending"}`;
  }
}

function renderEvolutionResult(data) {
  const root = $("#evolution-result");
  const decision = evolutionDecisions[data.decision] || data.decision || "评测请求已处理";
  const candidate = data.candidate || {};
  const baseline = data.baseline || {};
  const version = typeof data.version === "object" ? data.version?.version : data.version;
  const reasons = {
    "candidate prompt is identical to the active version": "候选提示词与当前版本相同，无需重复评测。",
    "candidate prompt failed the deterministic safety/completeness gate": "候选内容未通过安全或完整性检查，请调整后重试。",
    "candidate saved but no LLM provider is configured; replay evaluation was not run": "候选已保存。配置审查模型后即可运行回放评测。",
    "candidate saved but the validation dataset is smaller than the activation minimum": "候选已保存。验证案例数量不足，补充案例后再评测。",
    "candidate saved but the holdout dataset is smaller than the activation minimum": "候选已保存。独立测试案例不足，补充案例后再评测。",
    "candidate improved on validation and passed the non-regression holdout gate": "候选效果提升，且独立测试集未出现退步，已激活新版本。",
    "candidate passed replay gates and is awaiting shadow/canary approval": "候选已通过回放评测，等待后续灰度验证。",
    "no new supported learning signal was found in unresolved feedback": "当前反馈中没有可用于生成新候选的改进依据。",
  };
  const reason = reasons[data.reason] || data.reason || data.note || "";
  root.classList.remove("empty");
  root.innerHTML = `<div class="evolution-result-head"><strong>${escapeHtml(decision)}</strong>
      ${version != null ? `<span class="status status-neutral">版本 ${escapeHtml(version)}</span>` : ""}</div>
    ${reason ? `<p>${escapeHtml(reason)}</p>` : ""}
    ${candidate.score != null || baseline.score != null ? `<p class="submission-meta">候选得分 ${Number(candidate.score || 0).toFixed(3)} · 当前版本 ${Number(baseline.score || 0).toFixed(3)}</p>` : ""}
    <details class="raw-block"><summary>查看评测原始数据</summary><pre>${escapeHtml(formatJson(data))}</pre></details>`;
}

async function loadFailures() {
  if ($("#evolution-error")) $("#evolution-error").textContent = "";
  try {
    const [failuresData, status, runsData] = await Promise.all([
      api("/api/failures"),
      api("/v1/evolution/status"),
      api("/v1/evolution/runs?limit=5"),
    ]);
    renderEvolutionStatus(status);
    const cases = failuresData.cases || [];
    const runs = runsData.runs || [];
    const failureHtml = cases.length
      ? cases.slice(0, 8).map((item) => `
          <div class="task-row">
            <span class="task-main"><span class="task-glyph">FC</span><span class="task-copy">
              <span class="task-name">${escapeHtml(feedbackLabels[item.category] || item.category)}</span>
              <span class="task-meta"><span>${escapeHtml(item.task_id)}</span><span>${escapeHtml((item.payload || {}).note || "无说明")}</span></span>
            </span></span>
            <span class="status ${item.resolved ? "state-success" : "state-pending"}">${item.resolved ? "已解决" : "待处理"}</span>
          </div>`).join("")
      : '<div class="empty-state"><span><b>暂无失败反馈</b>系统当前没有未处理案例。</span></div>';
    const historyHtml = runs.length
      ? `<p class="list-section-label">最近评测</p>${runs.map((run) => `
          <div class="task-row">
            <span class="task-main"><span class="task-glyph">V${escapeHtml(run.candidate_version)}</span><span class="task-copy">
              <span class="task-name">${escapeHtml(evolutionDecisions[run.decision] || run.decision)}</span>
              <span class="task-meta">候选 ${Number(run.candidate_score || 0).toFixed(3)} · 当前版本 ${Number(run.baseline_score || 0).toFixed(3)}</span>
            </span></span>
          </div>`).join("")}`
      : "";
    $("#failure-list").innerHTML = failureHtml + historyHtml;
  } catch (error) {
    $("#evolution-status").textContent = "暂时无法读取评测状态。";
    if ($("#evolution-summary")) $("#evolution-summary").innerHTML = '<div class="empty-state"><span>评测状态读取失败，请刷新重试。</span></div>';
    if ($("#evolution-error")) $("#evolution-error").textContent = error.message;
    $("#failure-list").innerHTML = '<div class="empty-state"><span>反馈加载失败</span></div>';
    toast(error.message);
  }
}

$("#review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  const errorOutput = $("#review-error");
  if (errorOutput) errorOutput.textContent = "";
  if (modelAvailable === false) {
    if (errorOutput) errorOutput.textContent = "尚未配置审查模型，请先在服务环境中配置模型，再刷新后提交。";
    else toast("尚未配置审查模型，请配置模型后再提交。");
    return;
  }
  const body = { repository: String(values.get("repository") || "").trim(), diff: values.get("diff"), mode: values.get("mode") || "agentic" };
  if (values.get("pull_request")) body.pull_request = Number(values.get("pull_request"));
  const asyncQuery = values.get("async") ? "?async=true" : "";
  const output = $("#review-result");
  output.classList.remove("empty");
  output.textContent = "正在提交审查任务…";
  setButtonBusy(button, true, "正在提交…");
  try {
    const data = await api(`/v1/reviews${asyncQuery}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const id = data.task_id || data.id;
    const taskState = String(data.state || "PENDING").toUpperCase();
    output.innerHTML = `<div class="submission-state">
      <span class="status state-${escapeHtml(taskState.toLowerCase())}">${escapeHtml(stateLabels[taskState] || taskState)}</span>
      <h3>${taskState === "SUCCESS" ? "审查已完成" : "审查任务已提交"}</h3>
      <p>${taskState === "SUCCESS" ? "报告已生成，可以查看问题详情与修复建议。" : "任务已进入处理队列，可前往任务报告查看进展。"}</p>
      <p class="submission-meta">${escapeHtml(body.repository)}${body.pull_request ? ` · PR #${body.pull_request}` : " · 手动审查"}</p>
      ${id ? `<button class="button" type="button" data-submitted-task="${escapeHtml(id)}">查看任务报告</button>` : ""}
      <details class="raw-block"><summary>查看提交原始数据</summary><pre>${escapeHtml(formatJson(data))}</pre></details>
    </div>`;
    $("[data-submitted-task]", output)?.addEventListener("click", () => openTask(id));
    toast("审查任务已成功提交");
    loadDashboard();
  } catch (error) {
    if (errorOutput) errorOutput.textContent = `提交失败：${error.message}`;
    output.innerHTML = '<div class="empty-state"><span><b>审查尚未提交</b>请检查输入与服务配置后重试。</span></div>';
  } finally {
    setButtonBusy(button, false);
  }
});

function revealRaw(payload) {
  const raw = $("#task-raw-json");
  if (raw) raw.textContent = formatJson(payload);
  const block = $("#task-raw");
  if (block) block.open = true;
}

async function postTaskAction(path) {
  return api(`/v1/tasks/${encodeURIComponent(selectedTask)}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

$("#create-fix").addEventListener("click", async () => {
  if (!selectedTask) return;
  const button = $("#create-fix");
  setButtonBusy(button, true, "正在创建…");
  try {
    const data = await postTaskAction("fix");
    revealRaw(data);
    const status = String(data.status || "");
    const note = String(data.note || "").trim();
    if (status === "verified-draft") {
      toast(`修复分支已创建：${data.branch || "已推送"}`, 4200);
    } else if (status === "stale") {
      const reviewed = String(data.reviewed_sha || "").slice(0, 7);
      const current = String(data.current_sha || "").slice(0, 7);
      toast(`PR 已前进（${reviewed || "旧提交"} → ${current || "新提交"}），请重新审查后再修复`, 5600);
    } else if (status === "suggestion-only") {
      toast(`未创建分支：${note || "仅生成修复建议"}`, 5600);
    } else if (status === "blocked") {
      toast(`补丁被验证拦截：${note || "未通过结构或测试校验"}`, 5600);
    } else {
      toast(note || "修复流程已返回结果", 4200);
    }
    await openTask(selectedTask);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#task-cancel").addEventListener("click", async () => {
  if (!selectedTask) return;
  const button = $("#task-cancel");
  setButtonBusy(button, true, "正在取消…");
  try {
    const data = await postTaskAction("cancel");
    toast(data.cancel_requested ? "已提交取消请求" : "取消请求未被接受", 3600);
    await openTask(selectedTask);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#task-resume").addEventListener("click", async () => {
  if (!selectedTask) return;
  const button = $("#task-resume");
  setButtonBusy(button, true, "正在恢复…");
  try {
    const data = await postTaskAction("resume");
    const message = data.resumed
      ? "任务已重新入队"
      : data.state === "SUCCESS" ? "任务已完成，无需恢复" : "恢复请求已发送";
    toast(message, 3600);
    await openTask(selectedTask);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#copy-report").addEventListener("click", async () => {
  if (!selectedTask) return;
  const button = $("#copy-report");
  setButtonBusy(button, true, "准备中…");
  try {
    const response = await fetch(`/v1/tasks/${encodeURIComponent(selectedTask)}/report`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });
    if (!response.ok) throw new Error(`导出失败 (${response.status})`);
    const markdown = await response.text();
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(markdown);
      toast(`报告已复制（${markdown.length} 字符）`);
    } else {
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
      link.download = `pragent-report-${selectedTask.slice(0, 8)}.md`;
      link.click();
      URL.revokeObjectURL(link.href);
      toast("报告已下载为 Markdown");
    }
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#feedback-category").addEventListener("change", (event) => {
  const missed = event.target.value === "missed_issue";
  $("#feedback-missed-fields").classList.toggle("hidden", !missed);
  $("#feedback-hint").textContent = missed
    ? "补充规则和位置可让候选评测学习更精确的检查点。"
    : "提交后可在本任务和演进实验室查看状态。";
});

$("#feedback-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedTask || !selectedTaskData?.report) return;
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  const category = String(values.get("category"));
  const selectedIndex = values.get("finding_index");
  const findings = selectedTaskData.report.findings || [];
  const finding = selectedIndex === "" ? {} : { ...(findings[Number(selectedIndex)] || {}) };
  if (category === "missed_issue") {
    const ruleId = String(values.get("rule_id") || "").trim();
    const path = String(values.get("path") || "").trim();
    const line = Number(values.get("line"));
    if (ruleId) finding.rule_id = ruleId;
    if (path) finding.path = path;
    if (Number.isInteger(line) && line > 0) finding.line = line;
  }
  const output = $("#feedback-result");
  output.textContent = "正在保存反馈…";
  setButtonBusy(button, true, "正在提交…");
  try {
    const data = await api(`/v1/tasks/${encodeURIComponent(selectedTask)}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        category,
        finding: Object.keys(finding).length ? finding : null,
        note: String(values.get("note") || "").trim(),
      }),
    });
    output.textContent = `${feedbackLabels[data.category] || data.category}已记录；可在演进实验室等待候选评测。`;
    form.reset();
    $("#feedback-missed-fields").classList.add("hidden");
    $("#feedback-hint").textContent = "提交后可在本任务和演进实验室查看状态。";
    await Promise.all([loadTaskFeedback(selectedTask), loadDashboard()]);
    toast("反馈已记录");
  } catch (error) {
    output.textContent = `提交失败：${error.message}`;
  } finally {
    setButtonBusy(button, false);
  }
});

$("#reload-skills").addEventListener("click", async () => {
  const button = $("#reload-skills");
  setButtonBusy(button, true, "正在扫描…");
  try {
    await api("/v1/skills/reload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    await loadSkills();
    toast("Skills 已重新加载");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#evolution-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  if ($("#evolution-error")) $("#evolution-error").textContent = "";
  setButtonBusy(button, true, "正在评测…");
  try {
    const data = await api("/v1/evolution/propose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_name: values.get("skill_name"), prompt: values.get("prompt") }),
    });
    renderEvolutionResult(data);
    toast(evolutionDecisions[data.decision] || "评测请求已处理");
    loadFailures();
  } catch (error) {
    if ($("#evolution-error")) $("#evolution-error").textContent = `评测失败：${error.message}`;
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#auto-evolve").addEventListener("click", async () => {
  const button = $("#auto-evolve");
  if ($("#evolution-error")) $("#evolution-error").textContent = "";
  setButtonBusy(button, true, "正在生成…");
  try {
    const data = await api("/v1/evolution/auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_name: "llm-review" }),
    });
    renderEvolutionResult(data);
    toast(evolutionDecisions[data.decision] || "反馈候选请求已处理");
    loadFailures();
  } catch (error) {
    if ($("#evolution-error")) $("#evolution-error").textContent = `候选生成失败：${error.message}`;
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#refresh").addEventListener("click", async () => {
  const button = $("#refresh");
  setButtonBusy(button, true, "刷新中…");
  const view = location.hash.slice(1) || "overview";
  try {
    if (view === "tasks") await Promise.all([loadTasks(), selectedTask && $("#view-tasks").classList.contains("is-detail") ? openTask(selectedTask) : Promise.resolve()]);
    else if (view === "skills") await loadSkills();
    else if (view === "evolution") await loadFailures();
    else await loadDashboard();
  } finally {
    setButtonBusy(button, false);
  }
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  setButtonBusy(button, true, "正在登录…");
  try {
    const data = await api("/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: values.get("username"),
        password: values.get("password"),
        tenant_id: values.get("tenant_id"),
      }),
    });
    accessToken = data.access_token;
    localStorage.setItem("pragent_token", accessToken);
    $("#login-overlay").classList.add("hidden");
    $("#logout").classList.remove("hidden");
    $("#login-error").textContent = "";
    await loadDashboard();
    const view = location.hash.slice(1);
    if (view === "tasks") await Promise.all([loadTasks(), selectedTask ? openTask(selectedTask) : Promise.resolve()]);
    else if (view === "skills") await loadSkills();
    else if (view === "evolution") await loadFailures();
  } catch (error) {
    $("#login-error").textContent = error.message;
  } finally {
    setButtonBusy(button, false);
  }
});

$("#logout").addEventListener("click", () => {
  accessToken = "";
  localStorage.removeItem("pragent_token");
  $("#login-overlay").classList.remove("hidden");
  $("#logout").classList.add("hidden");
});

const diffInput = $('textarea[name="diff"]', $("#review-form"));
const diffStats = $("#diff-stats");
const dropHint = $("#diff-drop-hint");
const diffFileInput = $("#review-file-input");

$("#upload-diff")?.addEventListener("click", () => diffFileInput?.click());
diffFileInput?.addEventListener("change", async () => {
  await loadDiffFile(diffFileInput.files?.[0]);
  diffFileInput.value = "";
});

function updateDiffStats() {
  const value = diffInput.value;
  const lines = value ? value.split(/\r?\n/).length : 0;
  diffStats.textContent = `${lines} 行，${value.length} 字符`;
}

async function loadDiffFile(file) {
  if (!file) return;
  if (file.size > 512 * 1024) {
    const message = "文件超过 512 KB，请拆分后再提交";
    if ($("#review-error")) $("#review-error").textContent = message;
    toast(message);
    return;
  }
  try {
    diffInput.value = await file.text();
    if ($("#review-error")) $("#review-error").textContent = "";
    updateDiffStats();
    diffInput.focus();
    toast(`已载入 ${file.name}`);
  } catch (error) {
    toast(`文件读取失败：${error.message}`);
  }
}

diffInput.addEventListener("input", updateDiffStats);
updateDiffStats();

["dragenter", "dragover"].forEach((type) => {
  diffInput.addEventListener(type, (event) => {
    event.preventDefault();
    dropHint.classList.add("is-active");
  });
});
["dragleave", "drop", "dragend"].forEach((type) => {
  diffInput.addEventListener(type, () => dropHint.classList.remove("is-active"));
});
diffInput.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  event.preventDefault();
  loadDiffFile(file);
});

if (accessToken) $("#logout").classList.remove("hidden");

/* 使用说明：渲染仓库里的 docs/USER_GUIDE.md。
   手册只保留一份文件，仓库和控制台读的是同一份内容。 */

const guideState = { html: "", toc: [], loaded: false };

function inlineMarkdown(text) {
  // Escape first: the replacements below are the only real tags in the output.
  let value = escapeHtml(text);
  value = value.replace(/`([^`]+)`/g, "<code>$1</code>");
  value = value.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  value = value.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => {
    if (!/^(https?:\/\/|\.{0,2}\/)/.test(href)) return label;
    const external = href.startsWith("http");
    return `<a href="${href}"${external ? ' target="_blank" rel="noopener noreferrer"' : ""}>${label}</a>`;
  });
  return value;
}

function splitTableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function renderGuideMarkdown(source) {
  const lines = String(source).replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  const toc = [];
  let index = 0;
  let section = 0;

  // A paragraph ends where the next block-level construct starts.
  const startsBlock = (line) =>
    /^(#{1,3}\s|```|>|\|)/.test(line) || /^\s*([-*]|\d+\.)\s+/.test(line);

  while (index < lines.length) {
    const line = lines[index];

    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const body = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push(
        `<pre class="guide-code"${language ? ` data-lang="${escapeHtml(language)}"` : ""}>` +
        `<code>${escapeHtml(body.join("\n"))}</code></pre>`
      );
      continue;
    }

    if (!line.trim()) {
      index += 1;
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2].trim();
      if (level === 1) {
        blocks.push(`<h1 class="guide-title">${inlineMarkdown(text)}</h1>`);
      } else {
        section += 1;
        const id = `guide-section-${section}`;
        blocks.push(`<h${level} id="${id}">${inlineMarkdown(text)}</h${level}>`);
        toc.push({ id, level, text: text.replace(/[`*]/g, "") });
      }
      index += 1;
      continue;
    }

    if (line.startsWith("|") && /^\|[\s:|-]*\|$/.test((lines[index + 1] || "").trim())) {
      const header = splitTableRow(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].startsWith("|")) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      const head = header.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("");
      const body = rows
        .map((row) => `<tr>${row.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("")}</tr>`)
        .join("");
      blocks.push(
        `<div class="guide-table"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
      );
      continue;
    }

    if (line.startsWith(">")) {
      const quoted = [];
      while (index < lines.length && lines[index].startsWith(">")) {
        quoted.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(`<blockquote>${inlineMarkdown(quoted.join(" "))}</blockquote>`);
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(`<ul>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(`<ol>${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ol>`);
      continue;
    }

    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    if (paragraph.length) {
      blocks.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    } else {
      // Anything the subset does not model still reaches the reader as text.
      blocks.push(`<p>${inlineMarkdown(line.trim())}</p>`);
      index += 1;
    }
  }

  return { html: blocks.join("\n"), toc };
}

function renderGuide() {
  const root = $("#guide-body");
  if (!root) return;
  root.innerHTML = guideState.html;
  const toc = $("#guide-toc");
  if (!toc) return;
  toc.innerHTML = guideState.toc.map((item) =>
    `<button class="guide-toc-item level-${item.level}" type="button" data-target="${item.id}">` +
    `${escapeHtml(item.text)}</button>`
  ).join("");
  $$(".guide-toc-item", toc).forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById(button.dataset.target)?.scrollIntoView({
        behavior: reduceMotion.matches ? "auto" : "smooth", block: "start",
      });
      $$(".guide-toc-item", toc).forEach((item) => item.classList.toggle("is-active", item === button));
    });
  });
}

async function loadGuide(force = false) {
  const root = $("#guide-body");
  if (!root) return;
  if (guideState.loaded && !force) {
    renderGuide();
    return;
  }
  root.innerHTML = '<div class="list-loading"></div><div class="list-loading"></div>';
  try {
    const text = await api("/guide");
    const { html, toc } = renderGuideMarkdown(text);
    guideState.html = html;
    guideState.toc = toc;
    guideState.loaded = true;
    renderGuide();
  } catch (error) {
    root.innerHTML = `<div class="empty-state"><span><b>手册读取失败</b>${escapeHtml(error.message)}。可以刷新页面重试。</span></div>`;
    const toc = $("#guide-toc");
    if (toc) toc.innerHTML = "";
  }
}

function applyTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  const button = $("#theme-toggle");
  if (button) {
    button.textContent = dark ? "浅色外观" : "深色外观";
    button.setAttribute("aria-label", dark ? "切换为浅色外观" : "切换为深色外观");
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#101216" : "#f6f7f9");
}

/* ---------- 接入向导 ---------- */
let onboardingStatus = null;

function onboardSetStep(step, status) {
  const node = $(`.onboard-step[data-step="${step}"]`);
  if (node) node.dataset.state = status;
}

function onboardBadge(selector, text, ok) {
  const node = $(selector);
  if (!node) return;
  node.textContent = text;
  node.className = `status ${ok ? "status-success" : "status-neutral"}`;
}

function renderOnboarding(status) {
  onboardingStatus = status;
  const llm = status.llm || {};
  const github = status.github || {};
  const webhook = status.webhook || {};

  onboardBadge("#onboard-llm-badge", llm.configured ? `已配置 · ${llm.model || "模型"}` : "未配置", Boolean(llm.configured));
  onboardSetStep("llm", llm.configured ? "done" : "active");

  const form = $("#onboard-llm-form");
  if (form) {
    if (!form.elements.url.value) form.elements.url.value = llm.base_url || "";
    if (!form.elements.model.value) form.elements.model.value = llm.model || "";
    form.elements.api_key.placeholder = llm.api_key_masked || "sk-...";
  }

  onboardBadge(
    "#onboard-github-badge",
    github.has_token ? `已连接 · ${github.account || github.token_masked || "令牌"}` : "未连接",
    Boolean(github.has_token),
  );
  onboardSetStep("github", github.has_token ? "done" : llm.configured ? "active" : "pending");

  const repoPanelBadge = $("#onboard-repo-count");
  if (!github.has_token && repoPanelBadge) repoPanelBadge.textContent = "尚未加载";

  const webhookPanel = $("#onboard-webhook-panel");
  if (webhookPanel) webhookPanel.classList.toggle("hidden", !webhook.available);
  const webhookUrl = $("#onboard-webhook-url");
  if (webhookUrl) webhookUrl.textContent = webhook.endpoint || "—";
  onboardBadge(
    "#onboard-webhook-badge",
    webhook.has_secret ? "已生成密钥" : webhook.available ? "未配置" : "不可用",
    Boolean(webhook.has_secret),
  );

  const pollHint = $("#onboard-poll-hint");
  if (pollHint) {
    const interval = Number(status.watch_interval_seconds || 180);
    const minutes = Math.max(1, Math.round(interval / 60));
    pollHint.textContent = `后台每 ${minutes} 分钟扫描一次已订阅仓库的新提交。`;
  }
}

function renderRepoList(repositories, watches) {
  const list = $("#onboard-repo-list");
  const count = $("#onboard-repo-count");
  if (!list) return;
  if (!repositories.length) {
    list.innerHTML = '<p class="muted">这个令牌下没有可访问的仓库。</p>';
    if (count) count.textContent = "0 个仓库";
    return;
  }
  if (count) count.textContent = `${repositories.length} 个仓库`;
  const subscribed = new Map((watches || []).map((item) => [item.repository, item]));
  list.innerHTML = repositories.map((repo) => {
    const record = subscribed.get(repo.full_name);
    const checked = record && Number(record.enabled) ? "checked" : "";
    const tags = [repo.private ? "私有" : "公开", repo.archived ? "已归档" : ""]
      .filter(Boolean).join(" · ");
    return `<label class="onboard-repo"><input type="checkbox" value="${escapeHtml(repo.full_name)}" ${checked}><span><b>${escapeHtml(repo.full_name)}</b><small>${escapeHtml(tags)}</small></span></label>`;
  }).join("");
}

async function loadOnboardRepositories(status) {
  try {
    const data = await api("/v1/onboarding/repositories?limit=100");
    renderRepoList(data.repositories || [], (status && status.watches) || []);
  } catch (error) {
    const list = $("#onboard-repo-list");
    if (list) list.innerHTML = `<p class="inline-error">${escapeHtml(error.message)}</p>`;
  }
}

async function loadOnboarding() {
  try {
    const status = await api("/v1/onboarding/status");
    renderOnboarding(status);
    if (status.github && status.github.has_token) {
      await loadOnboardRepositories(status);
    } else {
      const list = $("#onboard-repo-list");
      if (list) list.innerHTML = '<p class="muted">连接 GitHub 后这里会列出仓库。</p>';
    }
  } catch (error) {
    toast(error.message);
  }
}

async function probeGithubCli() {
  const box = $("#onboard-github-detected");
  if (box) {
    box.classList.remove("hidden");
    box.textContent = "正在检测本机 GitHub CLI…";
  }
  try {
    const report = await api("/v1/onboarding/probe-gh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!box) return;
    if (!report.found) {
      box.textContent = report.reason || "未检测到本机登录，请填写访问令牌。";
      return;
    }
    const scopeNote = report.missing_repo_scope
      ? "，但令牌缺少 repo 权限，请先执行 gh auth refresh -s repo"
      : "";
    box.innerHTML = `检测到 <b>${escapeHtml(report.account || "已登录账号")}</b>（${escapeHtml(report.token_masked)}）${escapeHtml(scopeNote)}。<button class="text-button" type="button" data-action="adopt">使用此身份</button>`;
  } catch (error) {
    if (box) box.textContent = error.message;
  }
}

async function adoptGithubCli() {
  const errorNode = $("#onboard-github-error");
  if (errorNode) errorNode.textContent = "";
  try {
    const saved = await api("/v1/onboarding/github", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "gh-cli" }),
    });
    toast(`已连接 GitHub：${saved.account || "账号"}`);
    await loadOnboarding();
  } catch (error) {
    if (errorNode) errorNode.textContent = error.message;
  }
}

async function submitOnboardLlm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const errorNode = $("#onboard-llm-error");
  if (errorNode) errorNode.textContent = "";
  setButtonBusy(button, true, "验证中…");
  try {
    const result = await api("/v1/onboarding/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: form.elements.url.value.trim(),
        model: form.elements.model.value.trim(),
        api_key: form.elements.api_key.value.trim(),
      }),
    });
    form.elements.api_key.value = "";
    toast(`模型已生效：${result.model}`);
    await loadOnboarding();
  } catch (error) {
    if (errorNode) errorNode.textContent = error.message;
  } finally {
    setButtonBusy(button, false);
  }
}

async function submitOnboardToken(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const errorNode = $("#onboard-github-error");
  if (errorNode) errorNode.textContent = "";
  const token = form.elements.token.value.trim();
  if (!token) {
    if (errorNode) errorNode.textContent = "请填写访问令牌，或先点击“重新检测本机登录”。";
    return;
  }
  setButtonBusy(button, true, "连接中…");
  try {
    const saved = await api("/v1/onboarding/github", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, source: "manual" }),
    });
    form.elements.token.value = "";
    toast(`已连接 GitHub：${saved.account || "账号"}`);
    await loadOnboarding();
  } catch (error) {
    if (errorNode) errorNode.textContent = error.message;
  } finally {
    setButtonBusy(button, false);
  }
}

async function saveOnboardWatches() {
  const button = $("#onboard-save-repos");
  const errorNode = $("#onboard-repos-error");
  if (errorNode) errorNode.textContent = "";
  const webhookReady = Boolean(onboardingStatus && onboardingStatus.webhook && onboardingStatus.webhook.available);
  const mode = webhookReady ? "both" : "poll";
  const enabled = $("#onboard-enable-poll") ? $("#onboard-enable-poll").checked : true;
  const checked = $$("#onboard-repo-list input[type=checkbox]").filter((node) => node.checked);
  const watches = checked.map((node) => ({ repository: node.value, mode, enabled }));
  setButtonBusy(button, true, "保存中…");
  try {
    const result = await api("/v1/onboarding/watches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watches }),
    });
    toast(`已保存 ${(result.watches || []).length} 个仓库`);
    onboardSetStep("repos", (result.watches || []).length ? "done" : "active");
    await loadOnboarding();
  } catch (error) {
    if (errorNode) errorNode.textContent = error.message;
  } finally {
    setButtonBusy(button, false);
  }
}

async function generateWebhookSecret() {
  const out = $("#onboard-webhook-secret-out");
  try {
    const result = await api("/v1/onboarding/webhook-secret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (out) {
      out.innerHTML = `Secret：<code>${escapeHtml(result.secret)}</code>（只显示这一次，请立即填入 GitHub）`;
    }
    toast("Secret 已生成");
    await loadOnboarding();
  } catch (error) {
    toast(error.message);
  }
}

async function waitForWebhookEvent() {
  const node = $("#onboard-webhook-status");
  if (!node) return;
  node.textContent = "正在等待 GitHub 推送事件，去目标仓库开一个 PR 试试…";
  const started = Date.now();
  const timer = setInterval(async () => {
    if (Date.now() - started > 120000) {
      clearInterval(timer);
      node.textContent = "两分钟内没有收到事件。请检查 Payload URL、Secret 与事件类型是否正确。";
      return;
    }
    try {
      const data = await api("/v1/onboarding/webhook/await");
      if (data.delivery) {
        clearInterval(timer);
        node.textContent = `已收到事件 ${data.delivery.delivery_id}（${formatTime(data.delivery.received_at)}）`;
      }
    } catch (error) {
      clearInterval(timer);
      node.textContent = error.message;
    }
  }, 5000);
}

$("#onboard-llm-form")?.addEventListener("submit", submitOnboardLlm);
$("#onboard-token-form")?.addEventListener("submit", submitOnboardToken);
$("#onboard-probe")?.addEventListener("click", probeGithubCli);
$("#onboard-save-repos")?.addEventListener("click", saveOnboardWatches);
$("#onboard-gen-secret")?.addEventListener("click", generateWebhookSecret);
$("#onboard-wait-event")?.addEventListener("click", waitForWebhookEvent);
$("#onboard-github-detected")?.addEventListener("click", (event) => {
  if (event.target.closest('[data-action="adopt"]')) adoptGithubCli();
});

applyTheme(localStorage.getItem("pragent_theme") || "light");
$("#theme-toggle")?.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("pragent_theme", theme);
  applyTheme(theme);
});

show(location.hash.slice(1) || "overview", false);
if (location.hash && location.hash !== "#overview") loadDashboard();
