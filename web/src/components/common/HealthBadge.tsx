import { Badge, Tag, Tooltip, type BadgeProps } from 'antd'

import { TONE_COLOR, TONE_HEX, type StatusStyle } from '../../theme'

const TONE_BADGE: Record<string, BadgeProps['status']> = {
  success: 'success',
  warning: 'warning',
  danger: 'error',
  info: 'processing',
  neutral: 'default',
  accent: 'default',
}

interface Props {
  style: StatusStyle
  tooltip?: string
  /** Use 'badge' for a dot+text layout, 'tag' (default) for a colored pill. */
  variant?: 'tag' | 'badge'
}

/**
 * Unified status indicator used across the console.
 *
 * Renders either an antd Tag with a leading dot, or a Badge with dot + text.
 * Color is never the only signal — the label text is always rendered.
 */
export default function HealthBadge({ style: s, tooltip, variant = 'tag' }: Props) {
  if (variant === 'badge') {
    const badge = <Badge status={TONE_BADGE[s.tone] ?? 'default'} text={s.label} />
    return tooltip ? <Tooltip title={tooltip}>{badge}</Tooltip> : badge
  }

  const tag = (
    <Tag color={TONE_COLOR[s.tone]} style={{ marginInlineEnd: 0 }}>
      <span
        aria-hidden
        style={{
          display: 'inline-block',
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: TONE_HEX[s.tone],
          marginInlineEnd: 6,
          verticalAlign: 'middle',
        }}
      />
      {s.label}
    </Tag>
  )
  return tooltip ? <Tooltip title={tooltip}>{tag}</Tooltip> : tag
}
