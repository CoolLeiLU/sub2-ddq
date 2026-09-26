import { Card, Table, Typography } from 'antd'

import type { GuardianEvent } from '../../api'
import { eventDetailLabel, eventScopeLabel, eventTypeLabel, severityStyle } from '../../theme'
import HealthBadge from '../common/HealthBadge'
import DataCell from '../common/DataCell'

interface Props {
  events: GuardianEvent[]
  loading: boolean
}

export default function EventTable({ events, loading }: Props) {
  return (
    <Card bordered={false} style={{ borderRadius: 8 }}>
      <Table<GuardianEvent>
        loading={loading}
        rowKey="event_id"
        dataSource={events}
        size="middle"
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
          pageSizeOptions: ['20', '50', '100'],
          showTotal: (total) => `共 ${total} 条事件`,
        }}
        columns={[
          {
            title: '产生时间',
            dataIndex: 'created_at',
            width: 180,
            render: (v: string) => (
              <DataCell>{new Date(v).toLocaleString('zh-CN')}</DataCell>
            ),
          },
          {
            title: '严重级别',
            dataIndex: 'severity',
            width: 110,
            render: (v: string) => (
              <HealthBadge style={severityStyle(v)} tooltip={v} />
            ),
          },
          {
            title: '事件类型',
            dataIndex: 'event_type',
            width: 200,
            render: (v: string) => (
              <Typography.Text title={v} strong style={{ fontSize: 13 }}>
                {eventTypeLabel(v)}
              </Typography.Text>
            ),
          },
          {
            title: '影响范围',
            dataIndex: 'group_id',
            width: 110,
            render: (v: string | null) => <DataCell>{eventScopeLabel(v)}</DataCell>,
          },
          {
            title: '事件摘要与上下文',
            dataIndex: 'message',
            render: (v: string, event) => (
              <Typography.Text style={{ overflowWrap: 'anywhere' }}>
                {eventDetailLabel({ message: v, details: event.details })}
              </Typography.Text>
            ),
          },
        ]}
        expandable={{
          expandedRowRender: (event) => (
            <div style={{ padding: 12, background: '#f8fafc', borderRadius: 6 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                原始事件元数据 (Payload)
              </Typography.Text>
              <Typography.Text
                code
                style={{
                  display: 'block',
                  fontSize: 12,
                  whiteSpace: 'pre-wrap',
                  overflowWrap: 'anywhere',
                  padding: 10,
                  background: '#ffffff',
                  border: '1px solid #e2e8f0',
                  borderRadius: 4,
                }}
              >
                {JSON.stringify(event.details, null, 2)}
              </Typography.Text>
            </div>
          ),
        }}
      />
    </Card>
  )
}
