import { useEffect, useState } from 'react'
import { Alert, Card, Select, Table, Tag, Typography } from 'antd'

import { api, type GuardianEvent } from '../api'

const SEVERITY_COLORS: Record<string, string> = {
  INFO: 'blue',
  WARNING: 'orange',
  ERROR: 'red',
  CRITICAL: 'red',
}

/** Guardian's own event log: state transitions, quarantine, recovery, plaza. */
export default function Events() {
  const [events, setEvents] = useState<GuardianEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [severity, setSeverity] = useState<string | undefined>(undefined)

  useEffect(() => {
    api
      .events(100)
      .then((page) => setEvents(page.items ?? []))
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  if (error) return <Alert type="error" message={error} showIcon />

  const filtered = severity ? events.filter((event) => event.severity === severity) : events

  return (
    <Card
      title="事件日志"
      extra={
        <Select
          allowClear
          placeholder="按级别筛选"
          style={{ width: 160 }}
          value={severity}
          onChange={setSeverity}
          options={['INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((value) => ({
            value,
            label: value,
          }))}
        />
      }
    >
      <Table<GuardianEvent>
        loading={loading}
        rowKey="event_id"
        dataSource={filtered}
        size="small"
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          {
            title: '时间',
            dataIndex: 'created_at',
            width: 180,
            render: (value: string) => new Date(value).toLocaleString('zh-CN'),
          },
          {
            title: '级别',
            dataIndex: 'severity',
            width: 100,
            render: (value: string) => (
              <Tag color={SEVERITY_COLORS[value] ?? 'default'}>{value}</Tag>
            ),
          },
          { title: '类型', dataIndex: 'event_type', width: 220 },
          { title: '渠道', dataIndex: 'channel_id', width: 80, render: (v: string | null) => v ?? '—' },
          { title: '分组', dataIndex: 'group_id', width: 80, render: (v: string | null) => v ?? '—' },
          { title: '说明', dataIndex: 'message' },
        ]}
        expandable={{
          expandedRowRender: (event) => (
            <Typography.Paragraph style={{ margin: 0 }}>
              <pre style={{ margin: 0, fontSize: 12 }}>
                {JSON.stringify(event.details, null, 2)}
              </pre>
            </Typography.Paragraph>
          ),
        }}
      />
    </Card>
  )
}
