import { Button, Card, Popconfirm, Progress, Table, Tag, Typography } from 'antd'

import type { Channel } from '../../api'
import { healthStyle, palette, upstreamStyle } from '../../theme'
import HealthBadge from '../common/HealthBadge'
import DataCell from '../common/DataCell'

interface Props {
  channels: Channel[]
  loading: boolean
  /** Runs a manual control action; resolves once the list has been refreshed. */
  onAction?: (channel: Channel, action: 'exclude' | 'include', key: string) => Promise<void>
}

export default function ChannelTable({ channels, loading, onAction }: Props) {
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
            render: (desired: boolean, row) => {
              // The manual control value decides the label: an excluded channel
              // is not merely paused, and rendering one as the other hides why
              // Guardian is skipping it.
              if (row.manual_control !== 'NONE') {
                return (
                  <HealthBadge
                    style={healthStyle(row.manual_control)}
                    tooltip={`手动控制：${row.manual_control}`}
                  />
                )
              }
              return (
                <Tag color={desired ? 'blue' : 'default'}>
                  {desired ? '允许调度' : '暂停调度'}
                </Tag>
              )
            },
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
          ...(onAction
            ? [
                {
                  title: '操作',
                  key: 'actions',
                  width: 120,
                  fixed: 'right' as const,
                  render: (_: unknown, row: Channel) => {
                    const excluded = row.manual_control === 'EXCLUDED'
                    const action = excluded ? 'include' : 'exclude'
                    const label = excluded ? '恢复调度' : '排除'
                    return (
                      <Popconfirm
                        title={excluded ? '恢复该渠道的调度？' : '排除该渠道？'}
                        description={
                          excluded
                            ? '恢复后 Guardian 会重新评估并按策略调度它。'
                            : '该渠道将立即停止调度，Guardian 不会自动恢复它。'
                        }
                        okText="确认"
                        cancelText="取消"
                        okButtonProps={{ danger: !excluded }}
                        onConfirm={() =>
                          onAction(row, action, `console-${Date.now()}-${row.channel_id}`)
                        }
                      >
                        <Button type="link" size="small" danger={!excluded} style={{ padding: 0 }}>
                          {label}
                        </Button>
                      </Popconfirm>
                    )
                  },
                },
              ]
            : []),
        ]}
      />
    </Card>
  )
}
