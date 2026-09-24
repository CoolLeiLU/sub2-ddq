import { useEffect, useState } from 'react'
import { Alert, Card, Progress, Table, Tag } from 'antd'

import { api, type Group } from '../api'

const HEALTH_COLORS: Record<string, string> = {
  HEALTHY: 'green',
  DEGRADED: 'orange',
  FUSED: 'red',
  STALE: 'default',
  WARMING_UP: 'blue',
  EXCLUDED: 'default',
}

/** Group inventory and the health of the channels backing each one. */
export default function Groups() {
  const [groups, setGroups] = useState<Group[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .groups()
      .then((page) => setGroups(page.items ?? []))
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  if (error) return <Alert type="error" message={error} showIcon />

  return (
    <Card title="分组">
      <Table<Group>
        loading={loading}
        rowKey="group_id"
        dataSource={groups}
        size="middle"
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: 'ID', dataIndex: 'group_id', width: 80 },
          { title: '名称', dataIndex: 'name' },
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
            width: 180,
            render: (score: number) => (
              <Progress percent={Math.round(score ?? 0)} size="small" />
            ),
          },
          { title: '渠道数', dataIndex: 'channel_count', width: 100 },
        ]}
      />
    </Card>
  )
}
