import { useEffect, useState } from 'react'
import { Alert, Card, Select, Table } from 'antd'

import StatusTag from '../components/StatusTag'
import { api, type GuardianEvent } from '../api'
import { severityStyle } from '../theme'

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
            label: severityStyle(value).label,
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
            render: (value: string) => (
              <span className="data-table">{new Date(value).toLocaleString('zh-CN')}</span>
            ),
          },
          {
            title: '级别',
            dataIndex: 'severity',
            width: 110,
            render: (value: string) => (
              <StatusTag style={severityStyle(value)} tooltip={value} />
            ),
          },
          { title: '类型', dataIndex: 'event_type', width: 220 },
          {
            title: '渠道',
            dataIndex: 'channel_id',
            width: 80,
            render: (value: string | null) => <span className="data-table">{value ?? '—'}</span>,
          },
          {
            title: '分组',
            dataIndex: 'group_id',
            width: 80,
            render: (value: string | null) => <span className="data-table">{value ?? '—'}</span>,
          },
          {
            title: '说明',
            dataIndex: 'message',
            render: (value: string) => <span className="wrap-anywhere">{value}</span>,
          },
        ]}
        expandable={{
          expandedRowRender: (event) => (
            <pre
              style={{
                margin: 0,
                fontSize: 12,
                background: '#f1f5f9',
                border: '1px solid #e2e8f0',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-lg)',
                overflowX: 'auto',
              }}
            >
              {JSON.stringify(event.details, null, 2)}
            </pre>
          ),
        }}
      />
    </Card>
  )
}
