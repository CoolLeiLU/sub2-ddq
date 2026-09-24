import { useEffect, useState } from 'react'
import { Alert, Card, Input, Progress, Space, Table, Tag, Typography } from 'antd'

import { api, type Channel } from '../api'

const HEALTH_COLORS: Record<string, string> = {
  HEALTHY: 'green',
  DEGRADED: 'orange',
  FUSED: 'red',
  STALE: 'default',
  WARMING_UP: 'blue',
  EXCLUDED: 'default',
  MANUALLY_PAUSED: 'purple',
  PENDING: 'default',
}

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
          { title: 'ID', dataIndex: 'channel_id', width: 70 },
          { title: '名称', dataIndex: 'name', width: 180 },
          {
            title: '健康',
            dataIndex: 'health',
            width: 130,
            render: (health: string) => (
              <Tag color={HEALTH_COLORS[health] ?? 'default'}>{health}</Tag>
            ),
          },
          {
            title: '评分',
            dataIndex: 'score',
            width: 160,
            render: (score: number) => (
              <Progress
                percent={Math.round(score)}
                size="small"
                status={score >= 75 ? 'success' : score >= 50 ? 'normal' : 'exception'}
              />
            ),
          },
          {
            title: '置信度',
            dataIndex: 'confidence',
            width: 90,
            render: (value: number) => `${Math.round(value * 100)}%`,
          },
          {
            title: '延迟',
            dataIndex: 'latency_ms',
            width: 100,
            render: (value: number | null) => (value === null ? '—' : `${value} ms`),
          },
          {
            title: '上游状态',
            dataIndex: 'upstream_status',
            width: 110,
            render: (status: string) => (
              <Tag color={status === 'operational' ? 'green' : status === 'error' ? 'red' : 'orange'}>
                {status}
              </Tag>
            ),
          },
          {
            title: '调度',
            dataIndex: 'desired_schedulable',
            width: 90,
            render: (desired: boolean, row) =>
              row.manual_control !== 'NONE' ? (
                <Tag color="purple">{row.manual_control}</Tag>
              ) : (
                <Tag color={desired ? 'green' : 'default'}>{desired ? '可调度' : '已暂停'}</Tag>
              ),
          },
          {
            title: '数据新鲜度',
            dataIndex: 'freshness_state',
            width: 110,
            render: (state: string) => <Typography.Text type="secondary">{state}</Typography.Text>,
          },
        ]}
      />
      <Space style={{ marginTop: 12 }}>
        <Typography.Text type="secondary">共 {filtered.length} 个渠道</Typography.Text>
      </Space>
    </Card>
  )
}
