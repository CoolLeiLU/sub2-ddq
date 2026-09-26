import { Card, Progress, Table, Typography } from 'antd'

import type { Group } from '../../api'
import { healthStyle, palette } from '../../theme'
import HealthBadge from '../common/HealthBadge'
import DataCell from '../common/DataCell'
import GroupAccountsSubTable from './GroupAccountsSubTable'

interface Props {
  groups: Group[]
  loading: boolean
}

export default function GroupTable({ groups, loading }: Props) {
  return (
    <Card bordered={false} style={{ borderRadius: 8 }}>
      <Table<Group>
        loading={loading}
        rowKey="group_id"
        dataSource={groups}
        size="middle"
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          showTotal: (total) => `共 ${total} 个分组`,
        }}
        columns={[
          {
            title: '分组 ID',
            dataIndex: 'group_id',
            width: 90,
            render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
          },
          {
            title: '分组名称',
            dataIndex: 'name',
            width: 220,
            render: (name: string, group) => (
              <span>
                {name}
                {group.excluded && (
                  <Typography.Text type="secondary" style={{ marginLeft: 6, fontSize: 12 }}>
                    (已排除)
                  </Typography.Text>
                )}
              </span>
            ),
          },
          {
            title: '健康状态',
            dataIndex: 'health',
            width: 130,
            render: (health: string) => (
              <HealthBadge style={healthStyle(health)} tooltip={health} />
            ),
          },
          {
            title: '综合健康评分',
            dataIndex: 'score',
            width: 200,
            sorter: (a, b) => (a.score ?? 0) - (b.score ?? 0),
            render: (score: number) => (
              <Progress
                percent={Math.round(score ?? 0)}
                size="small"
                strokeColor={palette.primary}
              />
            ),
          },
          {
            title: '绑定渠道数',
            dataIndex: 'channel_count',
            width: 120,
            align: 'right',
            sorter: (a, b) => a.channel_count - b.channel_count,
            render: (v: number) => <DataCell>{v}</DataCell>,
          },
        ]}
        expandable={{
          expandedRowRender: (group) => (
            <div style={{ margin: '8px 0', padding: '12px 16px', background: '#fafafa', borderRadius: 6 }}>
              <Typography.Title level={5} style={{ marginTop: 0, marginBottom: 12, fontSize: 13 }}>
                分组下纳管账号清单
              </Typography.Title>
              <GroupAccountsSubTable accounts={group.accounts ?? []} />
            </div>
          ),
          rowExpandable: (group) => (group.accounts?.length ?? 0) > 0,
        }}
      />
    </Card>
  )
}
