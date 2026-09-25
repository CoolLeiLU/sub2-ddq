import { useEffect, useState } from 'react'
import { Alert, Card, Input, Progress, Space, Table, Tag, Typography } from 'antd'

import StatusTag from '../components/StatusTag'
import { api, type Channel } from '../api'
import { healthStyle, palette, upstreamStyle } from '../theme'

/** Channel inventory with health, score and scheduling intent. */
export default function Channels() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')

  useEffect(() => {
    api
      .channels()
      .then((page) => setChannels(page.items))
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  const filtered = channels.filter((channel) => {
    const needle = query.trim().toLowerCase()
    if (!needle) return true
    return (
      channel.name.toLowerCase().includes(needle) ||
      channel.channel_id.includes(needle) ||
      channel.health.toLowerCase().includes(needle)
    )
  })

  if (error) return <Alert type="error" message={error} showIcon />

  return (
    <Card
      title="渠道"
      extra={
        <Input.Search
          allowClear
          placeholder="按名称、ID 或健康状态筛选"
          style={{ width: 280 }}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      }
    >
      <Table<Channel>
        loading={loading}
        rowKey="channel_id"
        dataSource={filtered}
        size="middle"
        pagination={{ pageSize: 20, showSizeChanger: false }}
        scroll={{ x: 900 }}
        columns={[
          {
            title: 'ID',
            dataIndex: 'channel_id',
            width: 70,
            render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
          },
          { title: '名称', dataIndex: 'name', width: 180 },
          {
            title: '健康',
            dataIndex: 'health',
            width: 130,
            render: (health: string) => <StatusTag style={healthStyle(health)} tooltip={health} />,
          },
          {
            title: '评分',
            dataIndex: 'score',
            width: 160,
            render: (score: number) => (
              <Progress
                percent={Math.round(score)}
                size="small"
                strokeColor={
                  score >= 75
                    ? palette.primary
                    : score >= 50
                      ? palette.accent
                      : palette.destructive
                }
              />
            ),
          },
          {
            title: '置信度',
            dataIndex: 'confidence',
            width: 90,
            align: 'right',
            render: (value: number) => (
              <span className="data-table">{Math.round(value * 100)}%</span>
            ),
          },
          {
            title: '延迟',
            dataIndex: 'latency_ms',
            width: 100,
            align: 'right',
            render: (value: number | null) => (
              <span className="data-table">{value === null ? '—' : `${value} ms`}</span>
            ),
          },
          {
            title: '上游状态',
            dataIndex: 'upstream_status',
            width: 110,
            render: (status: string) => (
              <StatusTag style={upstreamStyle(status)} tooltip={status} />
            ),
          },
          {
            title: '调度',
            dataIndex: 'desired_schedulable',
            width: 100,
            render: (desired: boolean, row) =>
              row.manual_control !== 'NONE' ? (
                <Tag color="purple" style={{ marginInlineEnd: 0 }}>
                  {healthStyle('MANUALLY_PAUSED').label}
                </Tag>
              ) : (
                <Tag color={desired ? 'blue' : 'default'} style={{ marginInlineEnd: 0 }}>
                  {desired ? '可调度' : '已暂停'}
                </Tag>
              ),
          },
          {
            title: '数据新鲜度',
            dataIndex: 'freshness_state',
            width: 120,
            render: (state: string) => <Typography.Text type="secondary">{state}</Typography.Text>,
          },
        ]}
      />
      <Space style={{ marginTop: 'var(--space-lg)' }}>
        <Typography.Text type="secondary">共 {filtered.length} 个渠道</Typography.Text>
      </Space>
    </Card>
  )
}
