const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

let apiKey = "";
let currentPage = "overview";
let policyState = null;
let policyDefaults = null;
let eventsCursor = null;
let eventItems = [];
let groupsState = [];

const pageMeta = {
  overview: ["总览", "Guardian 全局运行状态与健康快照"],
  groups: ["分组调度", "分组健康、可用池与独立策略覆盖"],
  channels: ["渠道池", "渠道评分、状态和人工控制"],
  recovery: ["账号恢复", "异常账号、开放故障事件与恢复任务"],
  events: ["事件日志", "运行、状态迁移和人工操作审计"],
  policy: ["策略配置", "全局规则、系统参数与守护范围"],
  connection: ["连接设置", "上游、API 和存储状态"],
  info: ["信息", "版本信息和守护事件说明"],
};

const eventTypeLabels = {
  CHANNEL_HEALTHY: "渠道恢复健康",
  CHANNEL_DEGRADED: "渠道降级",
  CHANNEL_RATE_LIMITED: "渠道限流",
  CHANNEL_FUSED: "渠道熔断",
  CHANNEL_FORCED_KEEP: "渠道保底",
  CHANNEL_PENDING: "渠道待评估",
  CHANNEL_PAUSE: "渠道被人工暂停",
  CHANNEL_RESUME: "渠道恢复调度",
  CHANNEL_EXCLUDE: "渠道被排除",
  CHANNEL_INCLUDE: "渠道重新纳入",
  CHANNEL_FUSE: "渠道人工熔断",
  CHANNEL_RECOVER: "渠道人工恢复",
  POLICY_UPDATED: "策略已更新",
  SCHEDULING_STARTED: "守护已启动",
  SCHEDULING_STOPPED: "守护已停止",
  GROUP_POLICY_UPDATED: "分组策略已更新",
  GROUP_POLICY_CLEARED: "分组覆盖已清除",
  CHANNEL_OVERRIDE_UPDATED: "渠道覆盖已更新",
  SNAPSHOT_BACKLOG_COMPACTED: "快照积压已合并",
  CHANNEL_GROUP_MAPPING_CONFLICT: "渠道分组映射冲突",
  MODEL_PLAZA_REFRESHED: "模型广场已刷新",
  RECOVERY_BUDGET_WARNING: "恢复预算告警",
  RECOVERY_BUDGET_EXHAUSTED: "恢复预算耗尽",
};

const severityLabels = {
  INFO: "信息",
  WARNING: "警告",
  ERROR: "错误",
};

const runStatusLabels = {
  SUCCEEDED: "成功",
  RUNNING: "运行中",
  FAILED: "失败",
  CANCELLED: "已取消",
  INTERRUPTED: "已中断",
};

const triggerLabels = {
  BAD_ACCOUNT_STATE: "异常账号快照",
  CHANNEL_ERROR: "渠道故障事件",
  HOURLY_ACTIVE_CHECK: "每小时健康检查",
  MANUAL: "手动触发",
  CONDITIONAL: "条件触发",
};

const actionLabels = {
  NO_CHANGE: "无变更",
  ENABLE: "启用",
  DISABLE: "禁用",
};

const sourceLabels = {
  SHARED_MONITOR: "共享监控",
  TRAFFIC: "历史流量",
  PROBE: "主动探测",
  RECOVERY_PROBE: "恢复探测",
  MANUAL_PROBE: "手动探测",
};

const sampleTypeLabels = {
  PERFECT: "完美响应",
  SLOW_TTFB: "首字缓慢",
  UPSTREAM_UNKNOWN: "上游未知",
  GATEWAY_ERROR: "网关错误",
  QUOTA_EXHAUSTED: "限额耗尽",
  PROBE_FAIL: "探测失败",
  FATAL: "致命错误",
};

const ownerLabels = {
  GUARDIAN: "Guardian 接管",
  SCHEDULER: "调度器接管",
};

const reasonLabels = {
  healthy: "恢复正常",
  score_degraded: "评分下降",
  fused: "已熔断",
  recovered: "已恢复",
  scope_pause: "守护范围暂停",
  warming_up: "预热中",
  excluded_group: "分组被排除",
  excluded_channel: "渠道被排除",
  outside_managed_groups: "不在守护分组内",
  group_guard_disabled: "分组守护已停用",
  round_fuse_limit: "达到本轮熔断上限",
  evidence_fresh: "证据新鲜",
  evidence_stale: "证据陈旧",
  evidence_expired: "证据过期",
};

const channelActionLabels = {
  probe: "探测",
  pause: "暂停",
  resume: "恢复",
  exclude: "排除",
  include: "纳入",
};

const recoveryResultLabels = {
  ENABLED: "已启用",
  DISABLED: "已禁用",
  INDETERMINATE: "不确定",
  SKIPPED: "已跳过",
};

const recoveryClassificationLabels = {
  AVAILABLE: "可恢复",
  MANUAL_PAUSE: "人工暂停",
  UPSTREAM_ERROR: "上游错误",
  DISABLED: "已禁用",
  SYSTEM_QUARANTINE: "系统隔离",
  EXCLUDED: "已排除",
};

const recoveryReasonLabels = {
  account_test_failed: "探测调用失败",
  test_identity_mismatch: "探测返回账号不一致",
  account_mutation_failed: "账号变更执行失败",
  mutation_identity_mismatch: "变更回读账号不一致",
  run_stopped_after_unverified_mutation: "存在未验证变更，本轮已停止",
  test_incomplete: "探测未完成（上游未给出结论）",
  healthy_no_change: "健康，无需变更",
  manual_pause: "人工暂停",
  expired: "账号已过期",
  temporary_unavailable: "临时不可用",
  account_state_unavailable: "账号状态不可用",
  already_enabled: "已处于启用状态",
  already_disabled: "已处于禁用状态",
  automatic_pause_preserved: "保留自动暂停",
  test_context_invalid: "探测上下文无效",
  invalid_test_result: "探测结果无效",
  invalid_disable_result: "禁用回读无效",
  slow_first_token: "首字延迟过慢",
  channel_test_failed: "渠道探测失败",
};

function recoveryReasonText(reason) {
  if (!reason) return "—";
  const raw = String(reason);
  if (raw.startsWith("shared_unmonitored_scope_test_")) {
    const testResult = raw.slice("shared_unmonitored_scope_test_".length);
    return `共享范围外不可写回（探测结果 ${testResult}）`;
  }
  return raw
    .split(":")
    .map((part) => recoveryReasonLabels[part] || part)
    .join(" → ");
}

const policyFields = [
  ["#p-scan", "scan_interval_seconds", "number"],
  ["#p-sampling-mode", "sampling.mode", "string"],
  ["#p-snapshot-interval", "sampling.shared_snapshot_interval_seconds", "number"],
  ["#p-bucket-seconds", "sampling.bucket_seconds", "number"],
  ["#p-fresh-seconds", "sampling.fresh_seconds", "number"],
  ["#p-expire-seconds", "sampling.expire_seconds", "number"],
  ["#p-warmup-buckets", "sampling.min_warmup_buckets", "number"],
  ["#p-probe-enabled", "probe.enabled", "boolean"],
  ["#p-probe-interval", "probe.interval_seconds", "number"],
  ["#p-recovery-budget-enabled", "recovery_budget.enabled", "boolean"],
  ["#p-recovery-budget-interval", "recovery_budget.interval_seconds", "number"],
  ["#p-recovery-budget-concurrency", "recovery_budget.concurrency", "number"],
  ["#p-recovery-channel-hourly", "recovery_budget.per_channel_hourly_requests", "number"],
  ["#p-recovery-daily-requests", "recovery_budget.daily_requests", "number"],
  ["#p-recovery-daily-tokens", "recovery_budget.daily_tokens", "number"],
  ["#p-account-recovery-cooldown", "account_recovery.retry_cooldown_seconds", "number"],
  ["#p-short-window", "scoring.short_window", "number"],
  ["#p-long-window", "scoring.long_window", "number"],
  ["#p-slow-ttfb", "scoring.slow_ttfb_ms", "number"],
  ["#p-latest-weight", "scoring.latest_weight", "number"],
  ["#p-short-ratio", "scoring.short_ratio", "number"],
  ["#p-decay", "scoring.decay", "number"],
  ["#p-short-minutes", "scoring.short_window_minutes", "number"],
  ["#p-long-minutes", "scoring.long_window_minutes", "number"],
  ["#p-short-half-life", "scoring.short_half_life_minutes", "number"],
  ["#p-long-half-life", "scoring.long_half_life_minutes", "number"],
  ["#p-confidence-degrade", "confidence.degrade_min", "number"],
  ["#p-confidence-fuse", "confidence.fuse_min", "number"],
  ["#p-confidence-recover", "confidence.recover_min", "number"],
  ["#p-traffic-enabled", "traffic.enabled", "boolean"],
  ["#p-traffic-refresh", "traffic.refresh_seconds", "number"],
  ["#p-traffic-lookback", "traffic.lookback_minutes", "number"],
  ["#p-traffic-max-samples", "traffic.max_samples_per_channel", "number"],
  ["#score-perfect", "scoring.event_scores.PERFECT", "number"],
  ["#score-slow", "scoring.event_scores.SLOW_TTFB", "number"],
  ["#score-unknown", "scoring.event_scores.UPSTREAM_UNKNOWN", "number"],
  ["#score-gateway", "scoring.event_scores.GATEWAY_ERROR", "number"],
  ["#score-quota", "scoring.event_scores.QUOTA_EXHAUSTED", "number"],
  ["#score-probe", "scoring.event_scores.PROBE_FAIL", "number"],
  ["#score-fatal", "scoring.event_scores.FATAL", "number"],
  ["#p-breaker-enabled", "breaker.enabled", "boolean"],
  ["#p-http-window", "breaker.http_window", "number"],
  ["#p-http-failures", "breaker.http_failures", "number"],
  ["#p-http-score", "breaker.http_score_below", "number"],
  ["#p-max-fuse", "breaker.max_switch_per_round", "number"],
  ["#p-fuse-cooldown", "breaker.fused_cooldown_seconds", "number"],
  ["#p-min-pool", "breaker.min_pool_size", "number"],
  ["#p-min-score", "breaker.min_pool_score", "number"],
  ["#p-latency-threshold", "breaker.latency_ttfb_ms", "number"],
  ["#p-degrade-score", "degrade.score_threshold", "number"],
  ["#p-recovery-score", "recovery.target_score", "number"],
  ["#p-recovery-count", "recovery.success_count", "number"],
  ["#p-recovery-hold", "recovery.hold_seconds", "number"],
  ["#p-group-mode", "scope.managed_group_mode", "string"],
  ["#p-managed-groups", "scope.managed_group_ids", "set"],
  ["#p-excluded-groups", "scope.excluded_group_ids", "set"],
  ["#p-account-types", "scope.managed_account_types", "set"],
  ["#p-platforms", "scope.managed_platforms", "set"],
  ["#p-paused-channels", "scope.paused_channel_ids", "set"],
  ["#p-excluded-channels", "scope.excluded_channel_ids", "set"],
];

function make(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== "") element.textContent = String(text);
  return element;
}

function cell(row, value, className = "") {
  const td = make("td", className);
  if (value instanceof Node) td.append(value);
  else td.textContent = value == null ? "—" : String(value);
  row.append(td);
  return td;
}

function statusBadge(value) {
  const labels = {
    HEALTHY: "健康",
    DEGRADED: "降级",
    RATE_LIMITED: "限流",
    FUSED: "熔断",
    FORCED_KEEP: "强制保底",
    MANUALLY_PAUSED: "人工暂停",
    EXCLUDED: "已排除",
    PENDING: "待评分",
    NONE: "无",
    PAUSED: "暂停",
  };
  const className = ["FUSED", "EXCLUDED"].includes(value)
    ? "danger"
    : ["DEGRADED", "RATE_LIMITED", "FORCED_KEEP", "MANUALLY_PAUSED", "PAUSED"].includes(value)
      ? "warning"
      : value === "HEALTHY"
        ? "success"
        : "neutral";
  return make("span", `badge ${className}`, labels[value] || value || "—");
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatNumber(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function formatAge(value) {
  if (!value) return "尚无快照";
  const ageSeconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (!Number.isFinite(ageSeconds)) return "时间无效";
  if (ageSeconds < 60) return `${ageSeconds} 秒前`;
  if (ageSeconds < 3600) return `${Math.floor(ageSeconds / 60)} 分钟前`;
  return `${Math.floor(ageSeconds / 3600)} 小时前`;
}

function getPath(object, path) {
  return path.split(".").reduce((current, key) => current?.[key], object);
}

function setPath(object, path, value) {
  const keys = path.split(".");
  let current = object;
  for (const key of keys.slice(0, -1)) {
    if (!current[key]) current[key] = {};
    current = current[key];
  }
  current[keys.at(-1)] = value;
}

function parseSet(value) {
  return [...new Set(value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean))];
}

function toast(message, error = false) {
  const item = make("div", `toast${error ? " error" : ""}`, message);
  $("#toast-region").append(item);
  window.setTimeout(() => item.remove(), 4200);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-API-Key", apiKey);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/guardian/v1${path}`, {
    ...options,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`服务返回了无法解析的响应（HTTP ${response.status}）`);
  }
  if (!response.ok || !payload.ok) {
    const error = new Error(payload.error?.message || `请求失败（HTTP ${response.status}）`);
    error.code = payload.error?.code || "HTTP_ERROR";
    error.status = response.status;
    if (response.status === 401) showLogin("连接已失效，请重新输入 API Key");
    throw error;
  }
  return payload.data;
}

function showLogin(message = "") {
  apiKey = "";
  $("#app-shell").hidden = true;
  $("#login-screen").hidden = false;
  $("#login-message").textContent = message;
  $("#api-key").value = "";
  $("#api-key").focus();
}

function showApp() {
  $("#login-screen").hidden = true;
  $("#app-shell").hidden = false;
}

function openSidebar() {
  $("#sidebar").classList.add("open");
  $("#sidebar-scrim").hidden = false;
}

function closeSidebar() {
  $("#sidebar").classList.remove("open");
  $("#sidebar-scrim").hidden = true;
}

async function navigate(page) {
  if (!pageMeta[page]) return;
  currentPage = page;
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.page === page));
  $$(".page").forEach((item) => item.classList.toggle("active", item.id === `page-${page}`));
  $("#page-title").textContent = pageMeta[page][0];
  $("#page-subtitle").textContent = pageMeta[page][1];
  closeSidebar();
  $("#main-content").focus({ preventScroll: true });
  try {
    await refreshPage(page);
  } catch (error) {
    toast(error.message, true);
  }
}

async function refreshPage(page = currentPage) {
  const loaders = {
    overview: loadOverview,
    groups: loadGroups,
    channels: loadChannels,
    recovery: loadRecovery,
    events: () => loadEvents(true),
    policy: loadPolicy,
    connection: loadConnection,
    info: loadStatus,
  };
  if (loaders[page]) await loaders[page]();
}

async function loadStatus() {
  const status = await api("/status");
  const enabledLabel = status.enabled ? "健康守护运行中" : "健康守护已停止";
  $("#metric-engine").textContent = enabledLabel;
  $("#sidebar-status").textContent = status.enabled ? "健康守护运行中" : "调度已停止";
  $("#mode-label").textContent = status.enabled ? "健康守护" : "调度已停止";
  $("#info-mode").textContent = status.enabled ? "健康守护运行中" : "健康守护已停止";
  $("#sidebar-dot").style.background = status.enabled ? "var(--green)" : "var(--amber)";
  $("#scheduling-start").hidden = status.enabled;
  $("#scheduling-stop").hidden = !status.enabled;
  const notice = $("#scheduling-notice");
  notice.className = `notice ${status.enabled ? "info" : "safe"}`;
  $("#scheduling-notice-title").textContent = status.enabled ? "健康守护运行中" : "健康守护已停止";
  $("#scheduling-notice-copy").textContent = status.enabled
    ? "健康评估与账号恢复已就绪；异常账号按冷却账本探测并验证恢复。"
    : "启动后将执行健康评估与账号恢复；人工暂停与排除项永不自动恢复。";
  const policyBadge = $("#policy-scheduling-state");
  if (policyBadge) {
    policyBadge.textContent = status.enabled ? "运行中" : "已停止";
    policyBadge.className = `badge ${status.enabled ? "success" : "neutral"}`;
  }
  return status;
}

async function loadOverview() {
  const [overview, status, events, sampling] = await Promise.all([
    api("/overview"),
    api("/status"),
    api("/events?limit=6"),
    api("/sampling/status"),
  ]);
  const counts = overview.health_counts || {};
  const healthy = counts.HEALTHY || 0;
  const risk = Object.entries(counts)
    .filter(([name]) => !["HEALTHY", "PENDING"].includes(name))
    .reduce((total, [, count]) => total + Number(count), 0);
  $("#metric-mode").textContent = "直接";
  $("#metric-channels").textContent = overview.channel_count;
  $("#metric-groups").textContent = `${overview.group_count} 个分组`;
  $("#metric-healthy").textContent = healthy;
  $("#metric-risk").textContent = risk;
  $("#metric-revision").textContent = overview.policy_revision;
  renderSamplingStatus(sampling);
  await loadStatus();
  renderDistribution(counts, overview.channel_count);
  renderLastRun(status.last_run);
  renderEvents($("#overview-events"), events.items || []);
}

async function loadRecovery() {
  const data = await api("/recovery/status?limit=20");
  const episodes = data.open_episodes || [];
  const runs = data.recent_runs || [];
  $("#recovery-owner").textContent = ownerLabels[data.owner] || data.owner || "Guardian 接管";
  $("#recovery-owner-note").textContent = `重试冷却 ${data.retry_cooldown_seconds || 900} 秒`;
  $("#recovery-snapshot").textContent = data.latest_abnormal_snapshot ? "待处理" : "无";
  $("#recovery-episodes").textContent = episodes.length;
  $("#recovery-runs").textContent = runs.length;

  const episodeList = $("#recovery-episode-list");
  episodeList.replaceChildren();
  if (!episodes.length) {
    episodeList.append(make("p", "empty", "暂无开放事件"));
  } else {
    episodes.forEach((item) => {
      const row = make("article", "recovery-item");
      const title = make("strong", "", `渠道 ${item.channel_id} · 分组 ${item.group_id || "未映射"}`);
      const meta = make("span", "muted", `开始于 ${formatDate(item.opened_at)}`);
      row.append(title, meta);
      episodeList.append(row);
    });
  }

  const runList = $("#recovery-run-list");
  runList.replaceChildren();
  if (!runs.length) {
    runList.append(make("p", "empty", "暂无恢复任务"));
  } else {
    runs.forEach((item) => {
      const row = make("article", "recovery-item expandable");
      const result = item.result || {};
      const title = make(
        "strong",
        "",
        `${triggerLabels[item.trigger] || item.trigger} · ${runStatusLabels[item.status] || item.status}`,
      );
      const meta = make(
        "span",
        "muted",
        `测试 ${result.tested || 0} · 启用 ${result.enabled || 0} · 禁用 ${result.disabled || 0} · 不确定 ${result.indeterminate || 0} · 跳过 ${result.skipped || 0} · ${formatDate(item.started_at || item.created_at)}`,
      );
      const toggle = make("button", "text-button recovery-toggle", "查看账号明细 ▾");
      toggle.type = "button";
      const detail = make("div", "recovery-detail");
      detail.hidden = true;
      toggle.addEventListener("click", () => {
        toggleRecoveryDetail(toggle, detail, item.run_id).catch((error) =>
          toast(error.message, true),
        );
      });
      row.append(title, meta, toggle, detail);
      runList.append(row);
    });
  }
}

async function toggleRecoveryDetail(toggle, detail, runId) {
  if (!detail.hidden) {
    detail.hidden = true;
    toggle.textContent = "查看账号明细 ▾";
    return;
  }
  if (!detail.dataset.loaded) {
    toggle.disabled = true;
    toggle.textContent = "加载中…";
    try {
      const data = await api(`/recovery/runs/${encodeURIComponent(runId)}`);
      renderRecoveryDetail(detail, data.results || []);
      detail.dataset.loaded = "1";
    } finally {
      toggle.disabled = false;
    }
  }
  detail.hidden = false;
  toggle.textContent = "收起明细 ▴";
}

function renderRecoveryDetail(root, results) {
  root.replaceChildren();
  if (!results.length) {
    root.append(make("p", "empty", "该任务没有账号级记录"));
    return;
  }
  const scroll = make("div", "table-scroll");
  const table = make("table");
  const thead = make("thead");
  const headRow = make("tr");
  for (const label of ["账号", "分类", "结果", "原因", "已探测", "时间"]) {
    headRow.append(make("th", "", label));
  }
  thead.append(headRow);
  const body = make("tbody");
  for (const item of results) {
    const row = make("tr");
    cell(row, `账号 ${item.account_id}`);
    cell(row, recoveryClassificationLabels[item.classification] || item.classification || "—");
    const resultBadge = make(
      "span",
      `badge ${item.result === "ENABLED" ? "success" : item.result === "DISABLED" ? "danger" : item.result === "INDETERMINATE" ? "warning" : "neutral"}`,
      recoveryResultLabels[item.result] || item.result || "—",
    );
    cell(row, resultBadge);
    cell(row, recoveryReasonText(item.reason));
    cell(row, item.tested ? "是" : "否");
    cell(row, formatDateTime(item.occurred_at));
    body.append(row);
  }
  table.append(thead, body);
  scroll.append(table);
  root.append(scroll);
}

async function setScheduling(enabled) {
  const action = enabled ? "启动健康守护" : "紧急停止健康守护";
  const warning = enabled
    ? "启用后会对符合安全条件的账号执行真实恢复写入。"
    : "停止后未开始的账号恢复会立即被阻断。";
  if (!window.confirm(`${action}？\n\n${warning}`)) return;
  const policy = (await api("/policy")).policy;
  const button = enabled ? $("#scheduling-start") : $("#scheduling-stop");
  button.disabled = true;
  try {
    await api(`/scheduling/${enabled ? "start" : "stop"}`, {
      method: "POST",
      headers: {
        "If-Match": String(policy.revision),
        "Idempotency-Key": `ui:scheduling:${enabled}:${policy.revision}:${Date.now()}`,
      },
      body: { confirm: true },
    });
    toast(`${action}成功`);
    await loadStatus();
    if (currentPage === "overview") await loadOverview();
  } finally {
    button.disabled = false;
  }
}

async function submitRecovery() {
  if (!window.confirm("确认处理当前待恢复账号吗？\n\n只会使用持久化异常证据，人工暂停账号不会被探测或修改。")) return;
  const button = $("#recovery-run");
  button.disabled = true;
  try {
    const data = await api("/recovery/runs", {
      method: "POST",
      headers: { "Idempotency-Key": `ui:recovery:${Date.now()}` },
      body: { confirm: true },
    });
    toast(`恢复任务已提交，队列 ${data.queue_count}`);
    await loadRecovery();
  } finally {
    button.disabled = false;
  }
}

function renderSamplingStatus(sampling) {
  const freshness = sampling.channels_by_freshness || {};
  const mode = sampling.mode === "SHARED" ? "共享" : "主动";
  const latestAge = formatAge(sampling.latest_snapshot_at);
  $("#sampling-mode").textContent = mode;
  $("#sampling-snapshot-age").textContent = latestAge;
  $("#sampling-latest-at").textContent = formatDate(sampling.latest_snapshot_at);
  $("#sampling-pending").textContent = sampling.pending_snapshots ?? 0;
  $("#sampling-consumed").textContent = Math.max(
    0,
    Number(sampling.shared_snapshots || 0) - Number(sampling.pending_snapshots || 0),
  );
  $("#sampling-freshness").textContent = `${freshness.FRESH || 0} / ${freshness.EXPIRED || 0}`;
  const healthy = sampling.latest_snapshot_at &&
    Date.now() - new Date(sampling.latest_snapshot_at).getTime() <= Number(sampling.expire_seconds || 600) * 1000;
  const badge = $("#sampling-health");
  badge.textContent = healthy ? "链路新鲜" : "快照过期";
  badge.className = `badge ${healthy ? "success" : "warning"}`;
}

function renderDistribution(counts, total) {
  const root = $("#health-distribution");
  root.replaceChildren();
  const order = ["HEALTHY", "DEGRADED", "FUSED", "FORCED_KEEP", "MANUALLY_PAUSED", "EXCLUDED", "PENDING"];
  const rows = order.filter((name) => counts[name]);
  if (!rows.length) {
    root.append(make("p", "empty", "同步后显示健康分布"));
    return;
  }
  for (const name of rows) {
    const row = make("div", "distribution-row");
    row.append(statusBadge(name));
    const track = make("div", "distribution-track");
    const riskClass = ["DEGRADED", "FORCED_KEEP", "MANUALLY_PAUSED"].includes(name)
      ? " risk"
      : ["FUSED", "EXCLUDED"].includes(name)
        ? " fused"
        : "";
    const fill = make("div", `distribution-fill${riskClass}`);
    fill.style.width = `${Math.max(3, (Number(counts[name]) / Math.max(1, total)) * 100)}%`;
    track.append(fill);
    row.append(track, make("strong", "", counts[name]));
    root.append(row);
  }
}

function renderLastRun(run) {
  const root = $("#last-run-details");
  root.replaceChildren();
  const values = run
    ? [
        ["状态", runStatusLabels[run.status] || run.status],
        ["开始时间", formatDateTime(run.started_at)],
        ["评估渠道", run.result?.channels_evaluated ?? "—"],
        ["状态转换", run.result?.state_transitions ?? "—"],
        ["预期差异", run.result?.expected_changes ?? "—"],
      ]
    : [["状态", "尚未运行"]];
  for (const [label, value] of values) {
    const wrapper = make("div");
    wrapper.append(make("dt", "", label), make("dd", "", value));
    root.append(wrapper);
  }
}

function eventTypeLabel(eventType) {
  return eventTypeLabels[eventType] || eventType || "未知事件";
}

function severityBadge(severity) {
  const value = String(severity || "INFO");
  const className = value === "ERROR" ? "danger" : value === "WARNING" ? "warning" : "neutral";
  return make("span", `badge ${className}`, severityLabels[value] || value);
}

function renderEvents(root, items, append = false) {
  if (!append) root.replaceChildren();
  if (!items.length && !append) {
    root.append(make("p", "empty", "暂无事件"));
    return;
  }
  for (const event of items) {
    const item = make("div", "event-item");
    const head = make("div", "event-head");
    head.append(
      make("span", `event-marker ${String(event.severity || "").toLowerCase()}`),
      severityBadge(event.severity),
      make("span", "event-type", eventTypeLabel(event.event_type)),
      make("span", "event-code", event.event_type || ""),
      make("time", "event-time", formatDateTime(event.created_at)),
    );
    item.append(head);
    item.append(make("p", "event-message", event.message || "—"));
    const meta = make("div", "event-meta");
    if (event.channel_id) meta.append(make("span", "", `渠道 ${event.channel_id}`));
    if (event.group_id) meta.append(make("span", "", `分组 ${event.group_id}`));
    const details = event.details || {};
    for (const [key, value] of Object.entries(details)) {
      if (value === null || value === undefined || value === "") continue;
      const text = typeof value === "object" ? JSON.stringify(value) : String(value);
      meta.append(make("span", "", `${key}: ${text}`));
    }
    if (meta.childElementCount) item.append(meta);
    root.append(item);
  }
}

async function loadGroups() {
  const data = await api("/groups");
  groupsState = data.items || [];
  const body = $("#groups-table");
  body.replaceChildren();
  $("#groups-empty").hidden = groupsState.length > 0;
  for (const group of groupsState) {
    const row = make("tr");
    const title = make("div");
    title.append(make("span", "cell-title", group.name), make("span", "cell-subtitle", `ID ${group.group_id}`));
    cell(row, title);
    cell(row, group.channel_count);
    cell(row, group.available_count);
    cell(row, make("span", "score-value", formatNumber(group.score)));
    cell(row, group.latency_ms == null ? "—" : `${formatNumber(group.latency_ms, 0)} ms`);
    const source = make("div", "table-actions");
    if (group.excluded) source.append(make("span", "badge danger", "已排除"));
    if (group.channel_count === 0) source.append(make("span", "badge neutral", "未接入渠道"));
    source.append(make("span", `badge ${group.override ? "neutral" : "success"}`, group.override ? "独立覆盖" : "继承全局"));
    cell(row, source);
    const actions = make("div", "table-actions");
    const settings = make("button", "table-action", "设置");
    settings.type = "button";
    settings.addEventListener("click", () => openGroupDialog(group));
    actions.append(settings);
    cell(row, actions);
    body.append(row);
  }
  updateGroupFilter();
}

function updateGroupFilter() {
  const select = $("#channel-group");
  const current = select.value;
  select.replaceChildren(new Option("全部分组", ""));
  for (const group of groupsState) select.append(new Option(group.name, group.group_id));
  select.value = current;
}

function openGroupDialog(group) {
  const policy = group.override?.policy || {};
  $("#group-id").value = group.group_id;
  $("#group-dialog-title").textContent = `${group.name} · 策略覆盖`;
  $("#group-min-pool").value = policy.min_pool_size ?? "";
  $("#group-probe-interval").value = policy.probe_interval_seconds ?? "";
  $("#group-clear").hidden = !group.override;
  $("#group-dialog").showModal();
}

async function saveGroupPolicy() {
  const groupId = $("#group-id").value;
  const patch = {};
  const minPool = $("#group-min-pool").value;
  const interval = $("#group-probe-interval").value;
  if (minPool !== "") patch.min_pool_size = Number(minPool);
  if (interval !== "") patch.probe_interval_seconds = Number(interval);
  await api(`/groups/${encodeURIComponent(groupId)}/policy`, {
    method: "PATCH",
    headers: { "Idempotency-Key": `ui:group:${groupId}:${Date.now()}` },
    body: patch,
  });
  $("#group-dialog").close();
  toast("分组策略已保存");
  await loadGroups();
}

async function clearGroupPolicy() {
  const groupId = $("#group-id").value;
  await api(`/groups/${encodeURIComponent(groupId)}/policy`, {
    method: "DELETE",
    headers: { "Idempotency-Key": `ui:group-clear:${groupId}:${Date.now()}` },
  });
  $("#group-dialog").close();
  toast("分组已恢复继承全局策略");
  await loadGroups();
}

async function loadChannels() {
  if (!groupsState.length) {
    const groups = await api("/groups");
    groupsState = groups.items || [];
    updateGroupFilter();
  }
  const params = new URLSearchParams({ limit: "200" });
  const query = $("#channel-query").value.trim();
  const group = $("#channel-group").value;
  const health = $("#channel-health").value;
  if (query) params.set("query", query);
  if (group) params.set("group_id", group);
  if (health) params.set("health", health);
  const data = await api(`/channels?${params}`);
  const items = data.items || [];
  const body = $("#channels-table");
  body.replaceChildren();
  $("#channels-empty").hidden = items.length > 0;
  for (const channel of items) body.append(channelRow(channel));
}

function channelRow(channel) {
  const row = make("tr");
  const title = make("button", "text-button");
  title.type = "button";
  title.textContent = channel.name;
  title.addEventListener("click", () => showChannel(channel.channel_id));
  const titleWrap = make("div");
  titleWrap.append(title, make("span", "cell-subtitle", `ID ${channel.channel_id}`));
  cell(row, titleWrap);
  cell(row, channel.group_id || "未分组");
  cell(row, make("span", "score-value", formatNumber(channel.score)));
  cell(row, make("span", "score-value", `${formatNumber(Number(channel.confidence || 0) * 100, 0)}%`));
  cell(row, freshnessBadge(channel.freshness_state));
  cell(row, channel.latency_ms == null ? "—" : `${channel.latency_ms} ms`);
  cell(row, statusBadge(channel.health));
  const expectedAction = channel.details?.expected_action;
  cell(row, make("span", `badge ${expectedAction === "NO_CHANGE" ? "success" : "warning"}`, actionLabels[expectedAction] || expectedAction || "—"));
  cell(row, statusBadge(channel.manual_control));
  const actions = make("div", "table-actions");
  actions.append(actionButton("探测", channel, "probe"));
  const pauseAction = channel.manual_control === "PAUSED" ? "resume" : "pause";
  actions.append(actionButton(pauseAction === "pause" ? "暂停" : "恢复", channel, pauseAction, pauseAction === "pause"));
  const excludeAction = channel.manual_control === "EXCLUDED" ? "include" : "exclude";
  actions.append(actionButton(excludeAction === "exclude" ? "排除" : "纳入", channel, excludeAction, excludeAction === "exclude"));
  cell(row, actions);
  return row;
}

function freshnessBadge(value) {
  const labels = { FRESH: "新鲜", STALE: "陈旧", EXPIRED: "过期" };
  const className = value === "FRESH" ? "success" : value === "STALE" ? "warning" : "danger";
  return make("span", `badge ${className}`, labels[value] || value || "—");
}

function actionButton(label, channel, action, dangerous = false) {
  const button = make("button", `table-action${dangerous ? " danger" : ""}`, label);
  button.type = "button";
  button.addEventListener("click", async () => {
    if (dangerous && !window.confirm(`确定要对渠道“${channel.name}”执行“${label}”吗？`)) return;
    try {
      await channelAction(channel.channel_id, action);
    } catch (error) {
      toast(error.message, true);
    }
  });
  return button;
}

async function channelAction(channelId, action) {
  await api(`/channels/${encodeURIComponent(channelId)}/actions`, {
    method: "POST",
    headers: { "Idempotency-Key": `ui:${action}:${channelId}:${Date.now()}` },
    body: { action },
  });
  toast(`渠道操作已提交：${channelActionLabels[action] || action}`);
  await refreshPage(currentPage);
}

async function showChannel(channelId) {
  const [channel, explanation] = await Promise.all([
    api(`/channels/${encodeURIComponent(channelId)}`),
    api(`/channels/${encodeURIComponent(channelId)}/explanation`),
  ]);
  $("#channel-dialog-title").textContent = channel.name;
  const root = $("#channel-detail");
  root.replaceChildren();
  const summary = make("div", "channel-summary");
  const probeDetails = channel.details || {};
  for (const [label, value] of [
    ["渠道 ID", channel.channel_id],
    ["分组", channel.group_id || "未分组"],
    ["健康分", formatNumber(channel.score)],
    ["置信度", `${formatNumber(Number(explanation.confidence || 0) * 100, 0)}%`],
    ["证据状态", freshnessBadge(explanation.freshness_state)],
    ["证据来源", (explanation.evidence_sources || []).map((name) => sourceLabels[name] || name).join("、") || "暂无"],
    ["预热桶数", explanation.warmup_buckets ?? 0],
    ["监控探测模型", probeDetails.probe_model || "未提供"],
    ["监控协议", probeDetails.probe_api_mode || "默认"],
    ["决策原因", reasonLabels[explanation.reason] || explanation.reason || "暂无"],
  ]) {
    const item = make("div");
    const valueNode = value instanceof Node ? value : make("strong", "", value);
    item.append(make("span", "", label), valueNode);
    summary.append(item);
  }
  root.append(summary, make("h3", "", "最近评分样本"));
  const samples = make("div", "sample-list");
  if (!channel.samples?.length) samples.append(make("p", "empty", "暂无评分样本"));
  for (const sample of channel.samples || []) {
    const row = make("div", "sample-row");
    row.append(
      make("span", "", sampleTypeLabels[sample.event_type] || sample.event_type),
      make("span", "", sourceLabels[sample.source] || sample.source),
      make("strong", "", sample.score),
      make("time", "", formatDate(sample.occurred_at)),
    );
    samples.append(row);
  }
  root.append(samples);
  const override = channel.override || {};
  $("#channel-settings-id").value = channel.channel_id;
  $("#channel-probe-model").value = override.probe_model ?? "";
  const dialog = $("#channel-dialog");
  if (!dialog.open) dialog.showModal();
}

async function saveChannelSettings(event) {
  event.preventDefault();
  const channelId = $("#channel-settings-id").value;
  await api(`/channels/${encodeURIComponent(channelId)}`, {
    method: "PATCH",
    headers: { "Idempotency-Key": `ui:channel:${channelId}:${Date.now()}` },
    body: {
      probe_model: $("#channel-probe-model").value.trim() || null,
    },
  });
  toast("渠道覆盖参数已保存");
  await showChannel(channelId);
  if (currentPage === "channels") await loadChannels();
}

async function loadEvents(reset = false) {
  if (reset) {
    eventsCursor = null;
    eventItems = [];
  }
  const params = new URLSearchParams({ limit: "50" });
  const severity = $("#event-severity").value;
  const type = $("#event-type").value.trim();
  if (severity) params.set("severity", severity);
  if (type) params.set("event_type", type);
  if (eventsCursor) params.set("cursor", eventsCursor);
  const data = await api(`/events?${params}`);
  eventItems.push(...(data.items || []));
  eventsCursor = data.next_cursor;
  renderEvents($("#events-list"), eventItems);
  $("#events-more").hidden = !eventsCursor;
}

function fillPolicy(policy) {
  for (const [selector, path, type] of policyFields) {
    const input = $(selector);
    const value = getPath(policy, path);
    if (type === "boolean") input.checked = Boolean(value);
    else if (type === "set") input.value = Array.isArray(value) ? value.join(", ") : "";
    else input.value = value ?? "";
  }
  $("#policy-revision").textContent = policy.revision;
  const schedulingState = $("#policy-scheduling-state");
  schedulingState.textContent = policy.enabled ? "运行中" : "已停止";
  schedulingState.className = `badge ${policy.enabled ? "success" : "neutral"}`;
  $("#policy-message").textContent = "尚无未保存修改";
}

function collectPolicy() {
  const patch = {};
  for (const [selector, path, type] of policyFields) {
    const input = $(selector);
    let value;
    if (type === "boolean") value = input.checked;
    else if (type === "number") value = Number(input.value);
    else if (type === "set") value = parseSet(input.value);
    else value = input.value;
    setPath(patch, path, value);
  }
  return patch;
}

async function loadPolicy() {
  const data = await api("/policy");
  policyState = data.policy;
  policyDefaults = data.defaults;
  fillPolicy(policyState);
}

async function savePolicy(event) {
  event.preventDefault();
  if (!policyState) return;
  const button = $("#policy-form button[type='submit']");
  button.disabled = true;
  try {
    const data = await api("/policy", {
      method: "PATCH",
      headers: {
        "If-Match": String(policyState.revision),
        "Idempotency-Key": `ui:policy:${policyState.revision}:${Date.now()}`,
      },
      body: collectPolicy(),
    });
    policyState = data.policy;
    fillPolicy(policyState);
    toast(`策略版本 ${policyState.revision} 已保存`);
    await loadStatus();
  } catch (error) {
    if (error.code === "POLICY_REVISION_CONFLICT") {
      $("#policy-message").textContent = "策略已被其他会话修改，请刷新后重试";
    }
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function loadConnection() {
  await loadStatus();
}

async function runCycle(source) {
  const button = source === "sync" ? $("#sync-button") : $("#run-button");
  button.disabled = true;
  const original = button.textContent;
  button.textContent = source === "sync" ? "同步中…" : "评估中…";
  try {
    const endpoint = source === "sync" ? "/syncs" : "/runs";
    const data = await api(endpoint, {
      method: "POST",
      headers: { "Idempotency-Key": `ui:${source}:${Date.now()}` },
      body: source === "sync" ? {} : { dry_run: true },
    });
    const count = data.result?.channels_evaluated ?? 0;
    toast(`${source === "sync" ? "同步" : "评估"}完成，共处理 ${count} 个渠道`);
    await refreshPage(currentPage);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  apiKey = $("#api-key").value;
  $("#login-message").textContent = "正在验证连接…";
  try {
    await api("/overview");
    $("#api-key").value = "";
    $("#login-message").textContent = "";
    showApp();
    await navigate("overview");
  } catch (error) {
    $("#login-message").textContent = error.message;
    apiKey = "";
  }
});

$("#toggle-key").addEventListener("click", () => {
  const input = $("#api-key");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  $("#toggle-key").textContent = show ? "隐藏" : "显示";
});

$$(".nav-item").forEach((item) => item.addEventListener("click", () => navigate(item.dataset.page)));
$$('[data-page-link]').forEach((item) => item.addEventListener("click", () => navigate(item.dataset.pageLink)));
$("#open-sidebar").addEventListener("click", openSidebar);
$("#close-sidebar").addEventListener("click", closeSidebar);
$("#sidebar-scrim").addEventListener("click", closeSidebar);
$("#logout-button").addEventListener("click", () => showLogin("已断开当前连接"));
$("#sync-button").addEventListener("click", () => runCycle("sync"));
$("#run-button").addEventListener("click", () => runCycle("run"));
$("#scheduling-start").addEventListener("click", () => {
  setScheduling(true).catch((error) => toast(error.message, true));
});
$("#scheduling-stop").addEventListener("click", () => {
  setScheduling(false).catch((error) => toast(error.message, true));
});
$("#recovery-run").addEventListener("click", () => {
  submitRecovery().catch((error) => toast(error.message, true));
});
$("#channel-filter").addEventListener("click", () => loadChannels().catch((error) => toast(error.message, true)));
$("#channel-query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadChannels().catch((error) => toast(error.message, true));
});
$("#event-filter").addEventListener("click", () => loadEvents(true).catch((error) => toast(error.message, true)));
$("#events-more").addEventListener("click", () => loadEvents(false).catch((error) => toast(error.message, true)));
$("#group-save").addEventListener("click", () => saveGroupPolicy().catch((error) => toast(error.message, true)));
$("#group-clear").addEventListener("click", () => clearGroupPolicy().catch((error) => toast(error.message, true)));
$("#close-channel-dialog").addEventListener("click", () => $("#channel-dialog").close());
$("#channel-settings").addEventListener("submit", (event) => {
  saveChannelSettings(event).catch((error) => toast(error.message, true));
});
$("#policy-form").addEventListener("submit", savePolicy);
$("#policy-form").addEventListener("input", () => {
  $("#policy-message").textContent = "有尚未保存的修改";
});
$("#policy-defaults").addEventListener("click", () => {
  if (policyDefaults) {
    fillPolicy({ ...policyDefaults, revision: policyState?.revision || 1 });
    $("#policy-message").textContent = "已载入默认值，点击保存后生效";
  }
});

$$('[data-policy-tab]').forEach((tab) => {
  tab.addEventListener("click", () => {
    const selected = tab.dataset.policyTab;
    $$('[data-policy-tab]').forEach((item) => {
      const active = item === tab;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", String(active));
    });
    $$(".policy-pane").forEach((pane) => {
      const active = pane.id === `policy-${selected}`;
      pane.classList.toggle("active", active);
      pane.hidden = !active;
    });
  });
});
