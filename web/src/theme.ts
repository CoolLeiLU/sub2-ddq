/**
 * Design tokens for the Guardian console.
 *
 * Single source of truth for the antd theme and for the status vocabulary the
 * pages share. Values mirror `styles/theme.css`; change both together.
 */

import type { ThemeConfig } from 'antd'

/** Brand and surface palette. Mirrors the CSS custom properties. */
export const palette = {
  primary: '#1e40af',
  primaryHover: '#1c3a9e',
  primaryActive: '#183182',
  onPrimary: '#ffffff',
  secondary: '#3b82f6',
  accent: '#d97706',
  background: '#f8fafc',
  surface: '#ffffff',
  muted: '#e9eef6',
  foreground: '#1e3a8a',
  text: '#0f172a',
  textSecondary: '#475569',
  textTertiary: '#64748b',
  border: '#dbeafe',
  borderStrong: '#c7d7f0',
  destructive: '#dc2626',
} as const

export const fontSans =
  '"Fira Sans", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, "Segoe UI", sans-serif'
export const fontMono =
  '"Fira Code", "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace'

/** The antd token overrides. */
export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: palette.primary,
    colorInfo: palette.secondary,
    colorSuccess: '#16a34a',
    colorWarning: palette.accent,
    colorError: palette.destructive,
    colorTextBase: palette.text,
    colorBgBase: palette.surface,
    colorBgLayout: palette.background,
    colorBorder: palette.border,
    colorBorderSecondary: palette.border,
    borderRadius: 8,
    borderRadiusLG: 12,
    fontFamily: fontSans,
    fontFamilyCode: fontMono,
    fontSize: 14,
    controlHeight: 36,
    // The overrides require a 44px interaction target on every control.
    controlHeightLG: 44,
    motionDurationMid: '0.2s',
    motionDurationSlow: '0.3s',
  },
  components: {
    Layout: {
      bodyBg: palette.background,
      headerBg: palette.surface,
      siderBg: palette.surface,
      headerHeight: 56,
      headerPadding: '0 24px',
    },
    Menu: {
      itemBorderRadius: 6,
      itemHeight: 40,
      itemSelectedBg: palette.muted,
      itemSelectedColor: palette.primary,
      itemActiveBg: palette.muted,
      iconSize: 16,
    },
    Card: {
      borderRadiusLG: 12,
      paddingLG: 20,
      headerFontSize: 15,
    },
    Table: {
      headerBg: palette.background,
      headerColor: palette.textSecondary,
      rowHoverBg: '#f1f5f9',
      borderColor: palette.border,
      cellPaddingBlockSM: 8,
      cellPaddingInlineSM: 12,
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
      fontWeight: 500,
    },
    Input: {
      activeShadow: `0 0 0 3px ${palette.primary}20`,
    },
    Descriptions: {
      labelBg: palette.background,
      titleMarginBottom: 12,
    },
    Tag: {
      defaultBg: '#f1f5f9',
      defaultColor: palette.textSecondary,
    },
    Statistic: {
      contentFontSize: 26,
      titleFontSize: 13,
    },
  },
}

/**
 * Health vocabulary for channels and groups.
 *
 * `tone` selects the shared status colors and `label` is always rendered
 * alongside the color: the page overrides forbid color as the only signal.
 */
export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'accent'

export interface StatusStyle {
  tone: StatusTone
  label: string
}

const STATUS_TONES: Record<string, StatusStyle> = {
  HEALTHY: { tone: 'success', label: '健康' },
  DEGRADED: { tone: 'warning', label: '降级' },
  FUSED: { tone: 'danger', label: '熔断' },
  STALE: { tone: 'neutral', label: '陈旧' },
  WARMING_UP: { tone: 'info', label: '预热中' },
  EXCLUDED: { tone: 'neutral', label: '已排除' },
  MANUALLY_PAUSED: { tone: 'accent', label: '人工暂停' },
  PENDING: { tone: 'neutral', label: '待定' },
}

export function healthStyle(health: string): StatusStyle {
  return STATUS_TONES[health] ?? { tone: 'neutral', label: health }
}

const SEVERITY_TONES: Record<string, StatusStyle> = {
  INFO: { tone: 'info', label: '信息' },
  WARNING: { tone: 'warning', label: '警告' },
  ERROR: { tone: 'danger', label: '错误' },
  CRITICAL: { tone: 'danger', label: '严重' },
}

export function severityStyle(severity: string): StatusStyle {
  return SEVERITY_TONES[severity] ?? { tone: 'neutral', label: severity }
}

const RUN_TONES: Record<string, StatusStyle> = {
  SUCCEEDED: { tone: 'success', label: '成功' },
  FAILED: { tone: 'danger', label: '失败' },
  RUNNING: { tone: 'info', label: '运行中' },
  CANCELLED: { tone: 'neutral', label: '已取消' },
  INTERRUPTED: { tone: 'warning', label: '已中断' },
}

export function runStyle(status: string): StatusStyle {
  return RUN_TONES[status] ?? { tone: 'neutral', label: status }
}

const UPSTREAM_TONES: Record<string, StatusStyle> = {
  operational: { tone: 'success', label: '正常' },
  error: { tone: 'danger', label: '异常' },
  degraded: { tone: 'warning', label: '降级' },
}

export function upstreamStyle(status: string): StatusStyle {
  return UPSTREAM_TONES[status] ?? { tone: 'warning', label: status }
}

/**
 * Account state vocabulary for the group account tables.
 *
 * The upstream status and the pause provenance are separate signals, so they
 * are resolved separately: an account can be `error` and also carry an
 * automatic pause. `schedulable` on an active account is ambiguous upstream,
 * so an unannotated pause always reads as the human one.
 */
const ACCOUNT_TONES: Record<string, StatusStyle> = {
  active: { tone: 'success', label: '正常' },
  error: { tone: 'danger', label: '异常' },
  disabled: { tone: 'danger', label: '已停用' },
  inactive: { tone: 'neutral', label: '未激活' },
}

export function accountStyle(status: string): StatusStyle {
  return ACCOUNT_TONES[status] ?? { tone: 'neutral', label: status }
}

/** Label for whether upstream is currently handing this account traffic. */
export function accountSchedulableStyle(schedulable: boolean): StatusStyle {
  return schedulable
    ? { tone: 'success', label: '可调度' }
    : { tone: 'warning', label: '不可调度' }
}

/**
 * Vocabulary for the Guardian event log.
 *
 * Both tables fall back to the raw identifier for anything missing here, so a
 * raw value on screen means a vocabulary entry was never added.
 */
const EVENT_TYPE_LABELS: Record<string, string> = {
  PERFECT: '请求正常',
  SLOW_TTFB: '响应偏慢',
  UPSTREAM_UNKNOWN: '上游状态未知',
  GATEWAY_ERROR: '网关错误',
  QUOTA_EXHAUSTED: '额度耗尽',
  PROBE_FAIL: '探测失败',
  FATAL: '致命错误',
  CHANNEL_GROUP_MAPPING_CONFLICT: '渠道与分组映射冲突',
  SNAPSHOT_BACKLOG_COMPACTED: '输入快照积压已清理',
  MODEL_PLAZA_REFRESHED: '模型广场已刷新',
  POLICY_UPDATED: '策略已更新',
  GROUP_POLICY_UPDATED: '分组策略已更新',
  GROUP_POLICY_CLEARED: '分组策略已清除',
  CHANNEL_OVERRIDE_UPDATED: '渠道调度覆盖已更新',
  SCHEDULING_STARTED: '调度已启动',
  SCHEDULING_STOPPED: '调度已停止',
  RECOVERY_BUDGET_WARNING: '恢复预算已达 80%',
  RECOVERY_BUDGET_EXHAUSTED: '恢复预算已耗尽',
}

/** Health values the backend embeds in `CHANNEL_<health>` event types. */
const CHANNEL_EVENT_SUFFIXES: Record<string, string> = {
  HEALTHY: '渠道恢复健康',
  DEGRADED: '渠道降级',
  FUSED: '渠道熔断',
  FORCED_KEEP: '渠道熔断但保留下限',
  EXCLUDED: '渠道已排除',
  MANUALLY_PAUSED: '渠道人工暂停',
  UPSTREAM_DISABLED: '渠道上游已禁用',
}

/** The Chinese label for an event type, or the raw type when unrecognised. */
export function eventTypeLabel(eventType: string): string {
  const known = EVENT_TYPE_LABELS[eventType]
  if (known) return known
  if (eventType.startsWith('CHANNEL_')) {
    const suffix = CHANNEL_EVENT_SUFFIXES[eventType.slice('CHANNEL_'.length)]
    if (suffix) return suffix
  }
  return eventType
}

/**
 * Label for the event scope column.
 *
 * The channel id is dropped: it is an upstream monitor id, so on this table it
 * is noise that the expanded detail can still show. An event with no group is a
 * console-wide one rather than an unassigned channel, so it reads as a global
 * scope instead of the em dash an empty cell would get.
 */
export function eventScopeLabel(groupId: string | null): string {
  return groupId ?? '全局'
}

/** Exact-match message vocabulary; the backend writes these verbatim. */
const EVENT_MESSAGE_LABELS: Record<string, string> = {
  'Expired Guardian input snapshots were superseded': '过期的输入快照已被新的采样取代',
  'Channel scheduling override updated': '渠道调度覆盖已更新',
  'Guardian direct scheduling started': 'Guardian 直接调度已启动',
  'Guardian direct scheduling stopped': 'Guardian 直接调度已停止',
  'Guardian recovery probe budget reached 80 percent': '恢复探测预算已用至 80%',
  'Guardian recovery probe budget exhausted': '恢复探测预算已耗尽',
  'Skipped channel-error expansion because the open episode has a different group mapping':
    '已有进行中的渠道错误事件映射到其他分组，本次未做渠道扩展',
}

/** Prefix-matched messages: the backend interpolates the identifier tail. */
const EVENT_MESSAGE_PREFIXES: [string, string][] = [
  ['Guardian policy revision ', 'Guardian 策略已保存，版本 '],
  ['Group ', '分组策略已更新：'],
  ['Model plaza refreshed: ', '模型广场已刷新：'],
  ['Manual channel action: ', '人工渠道操作：'],
]

/** Reason codes the state machine appends to a channel transition message. */
const REASON_LABELS: Record<string, string> = {
  healthy: '健康',
  warming_up: '预热中',
  manual_pause: '人工暂停',
  manual_fuse: '人工熔断',
  manual_exclusion: '人工排除',
  upstream_disabled: '上游已禁用',
  fuse_not_guardian_owned: '熔断非 Guardian 触发，不自动恢复',
  fused_cooldown: '熔断冷却中',
  usable_pool_slow_response: '可用池只剩慢速响应',
  recovery_threshold_met: '已满足恢复阈值',
  recovery_probe_disabled: '恢复探测已关闭',
  latency_degraded: '延迟降级',
  score_degraded: '评分降级',
  low_confidence: '证据不足，置信度偏低',
  daily_request_budget_exhausted: '当日请求预算已耗尽',
  daily_token_budget_exhausted: '当日 Token 预算已耗尽',
}

/** Freshness values the engine embeds as `evidence_<freshness>`. */
const EVIDENCE_LABELS: Record<string, string> = {
  fresh: '证据新鲜',
  stale: '证据陈旧',
  expired: '证据已过期',
}

/** The Chinese label for a transition reason code given in `details.reason`. */
export function reasonLabel(reason: string | null | undefined): string {
  if (!reason) return ''
  const minimumPool = reason.match(/^minimum_pool:(.+)$/)
  if (minimumPool) {
    const inner = reasonLabel(minimumPool[1])
    return `熔断会击穿最小可用池（${inner}）`
  }
  const evidence = reason.match(/^evidence_(\w+)$/)
  if (evidence) {
    return EVIDENCE_LABELS[evidence[1].toLowerCase()] ?? reason
  }
  return REASON_LABELS[reason] ?? reason
}

/** The Chinese label for an event message. */
export function eventMessageLabel(message: string): string {
  const exact = EVENT_MESSAGE_LABELS[message]
  if (exact) return exact
  for (const [prefix, label] of EVENT_MESSAGE_PREFIXES) {
    if (message.startsWith(prefix)) return `${label}${message.slice(prefix.length)}`
  }
  return message
}

/**
 * The event message column.
 *
 * A channel transition carries the raw decision reason in `details.reason`,
 * which says far more than the message's reason code does, so it is folded in
 * here instead of in `eventMessageLabel`: the message alone cannot see it.
 * The reason is omitted when the effect was NO_CHANGE, since the channel's
 * health did not actually move and a reason would misread as one that did.
 */
export function eventDetailLabel(event: {
  message: string
  details: Record<string, unknown>
}): string {
  const base = eventMessageLabel(event.message)
  if (event.details.action === 'NO_CHANGE') return base
  const reason = reasonLabel(
    typeof event.details.reason === 'string' ? event.details.reason : null,
  )
  return reason ? `${base}（${reason}）` : base
}

/** Map a tone onto the antd Tag color prop. */
export const TONE_COLOR: Record<StatusTone, string> = {
  success: 'success',
  warning: 'warning',
  danger: 'error',
  info: 'processing',
  neutral: 'default',
  accent: 'purple',
}

/** Map a tone onto the raw hex used for status dots and inline accents. */
export const TONE_HEX: Record<StatusTone, string> = {
  success: '#16a34a',
  warning: '#d97706',
  danger: '#dc2626',
  info: '#3b82f6',
  neutral: '#94a3b8',
  accent: '#7c3aed',
}
