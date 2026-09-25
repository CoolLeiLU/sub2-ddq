import { Tag, Tooltip } from 'antd'

import { TONE_COLOR, TONE_HEX, type StatusStyle } from '../theme'

/**
 * A status pill: a colored dot plus its text label.
 *
 * The page overrides require that color is never the only signal, so the
 * label is always rendered. Unknown values still show their raw text.
 */
export default function StatusTag({ style, tooltip }: { style: StatusStyle; tooltip?: string }) {
  const tag = (
    <Tag color={TONE_COLOR[style.tone]} style={{ marginInlineEnd: 0 }}>
      <span
        aria-hidden
        style={{
          display: 'inline-block',
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: TONE_HEX[style.tone],
          marginInlineEnd: 6,
          verticalAlign: 'middle',
        }}
      />
      {style.label}
    </Tag>
  )
  return tooltip ? <Tooltip title={tooltip}>{tag}</Tooltip> : tag
}
