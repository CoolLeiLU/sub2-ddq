import { Typography } from 'antd'

/** Monospace tabular-nums cell for numeric / identifier values in tables. */
export default function DataCell({ children }: { children: React.ReactNode }) {
  return (
    <Typography.Text
      style={{
        fontFamily: 'var(--font-mono)',
        fontVariantNumeric: 'tabular-nums',
        fontSize: 13,
      }}
    >
      {children}
    </Typography.Text>
  )
}
