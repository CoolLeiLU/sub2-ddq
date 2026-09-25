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
