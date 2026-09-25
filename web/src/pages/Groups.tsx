import { useEffect, useState } from 'react'
import { Alert, Card, Progress, Table, Typography } from 'antd'

import StatusTag from '../components/StatusTag'
import { api, type Group } from '../api'
import { healthStyle, palette } from '../theme'

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
          {
            title: 'ID',
            dataIndex: 'group_id',
            width: 80,
            render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
          },
          { title: '名称', dataIndex: 'name' },
          {
            title: '健康',
            dataIndex: 'health',
            width: 130,
            render: (health: string) => <StatusTag style={healthStyle(health)} tooltip={health} />,
          },
          {
            title: '评分',
            dataIndex: 'score',
            width: 180,
            render: (score: number) => (
              <Progress percent={Math.round(score ?? 0)} size="small" strokeColor={palette.primary} />
            ),
          },
          {
            title: '渠道数',
            dataIndex: 'channel_count',
            width: 100,
            align: 'right',
            render: (value: number) => <span className="data-table">{value}</span>,
          },
        ]}
      />
    </Card>
  )
}
