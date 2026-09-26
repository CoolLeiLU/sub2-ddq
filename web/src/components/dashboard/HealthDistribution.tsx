import { Card, Empty, Flex, Tag, Typography } from 'antd'

import { healthStyle, TONE_HEX } from '../../theme'
import DataCell from '../common/DataCell'

interface Props {
  counts: Record<string, number>
}

export default function HealthDistribution({ counts }: Props) {
  const entries = Object.entries(counts)

  return (
    <Card title="渠道健康状态分布" bordered={false} style={{ borderRadius: 8 }}>
      {entries.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无渠道健康数据" />
      ) : (
        <Flex wrap="wrap" gap={10}>
          {entries.map(([health, count]) => {
            const hs = healthStyle(health)
            return (
              <Tag
                key={health}
                color="default"
                style={{
                  padding: '6px 12px',
                  borderRadius: 6,
                  display: 'inline-flex',
                  alignItems: 'center',
                  fontSize: 13,
                }}
              >
                <span
                  aria-hidden
                  style={{
                    display: 'inline-block',
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: TONE_HEX[hs.tone],
                    marginInlineEnd: 8,
                  }}
                />
                <Typography.Text style={{ marginInlineEnd: 8 }}>{hs.label}</Typography.Text>
                <DataCell>
                  <strong>{count}</strong>
                </DataCell>
              </Tag>
            )
          })}
        </Flex>
      )}
    </Card>
  )
}
