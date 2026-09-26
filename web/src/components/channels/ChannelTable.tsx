import { Card, Progress, Table, Tag, Typography } from 'antd'

import type { Channel } from '../../api'
import { healthStyle, palette, upstreamStyle } from '../../theme'
import HealthBadge from '../common/HealthBadge'
import DataCell from '../common/DataCell'

interface Props {
  channels: Channel[]
  loading: boolean
}

export default function ChannelTable({ channels, loading }: Props) {
  return (
    <Card bordered={false} style={{ borderRadius: 8 }}>
      <Table<Channel>
        loading={loading}
        rowKey="channel_id"
        dataSource={channels}
        size="middle"
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50', '100'],
          showTotal: (total) => `共 ${total} 个渠道`,
        }}
        scroll={{ x: 1000 }}
        columns={[
          {
            title: '渠道 ID',
            dataIndex: 'channel_id',
            width: 80,
            render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
          },
          {
            title: '渠道名称',
            dataIndex: 'name',
            width: 180,
            ellipsis: true,
          },
          {
            title: '健康评级',
            dataIndex: 'health',
            width: 120,
            render: (health: string) => (
              <HealthBadge style={healthStyle(health)} tooltip={health} />
            ),
          },
          {
            title: '综合评分',
            dataIndex: 'score',
            width: 160,
            sorter: (a, b) => a.score - b.score,
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
            render: (v: number) => <DataCell>{Math.round(v * 100)}%</DataCell>,
          },
          {
            title: '响应延迟',
            dataIndex: 'latency_ms',
            width: 100,
            align: 'right',
            sorter: (a, b) => (a.latency_ms ?? 99999) - (b.latency_ms ?? 99999),
            render: (v: number | null) => (
              <DataCell>{v === null ? '—' : `${v} ms`}</DataCell>
            ),
          },
          {
            title: '上游监控',
            dataIndex: 'upstream_status',
            width: 110,
            render: (status: string) => (
              <HealthBadge style={upstreamStyle(status)} tooltip={status} />
            ),
          },
          {
            title: '调度决策',
            dataIndex: 'desired_schedulable',
            width: 110,
            render: (desired: boolean, row) =>
              row.manual_control !== 'NONE' ? (
                <Tag color="purple">{healthStyle('MANUALLY_PAUSED').label}</Tag>
              ) : (
                <Tag color={desired ? 'blue' : 'default'}>
                  {desired ? '允许调度' : '暂停调度'}
                </Tag>
              ),
          },
          {
            title: '数据时效',
            dataIndex: 'freshness_state',
            width: 120,
            render: (state: string) => (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {state}
              </Typography.Text>
            ),
          },
        ]}
      />
    </Card>
  )
}
