import { Space, Table, Tag, Typography } from 'antd'

import type { GroupAccount } from '../../api'
import { accountSchedulableStyle, accountStyle } from '../../theme'
import HealthBadge from '../common/HealthBadge'
import DataCell from '../common/DataCell'

const dateTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium' })

interface Props {
  accounts: GroupAccount[]
}

/** The accounts inside one group, shown when a group row is expanded. */
export default function GroupAccountsSubTable({ accounts }: Props) {
  if (accounts.length === 0) {
    return <Typography.Text type="secondary">该分组下暂无账号记录</Typography.Text>
  }

  return (
    <Table<GroupAccount>
      rowKey="account_id"
      dataSource={accounts}
      size="small"
      pagination={accounts.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
      columns={[
        {
          title: '账号 ID',
          dataIndex: 'account_id',
          width: 120,
          render: (v: string) => <DataCell>{v}</DataCell>,
        },
        {
          title: '健康状态',
          dataIndex: 'status',
          width: 110,
          render: (status: string) => <HealthBadge style={accountStyle(status)} tooltip={status} />,
        },
        {
          title: '调度状态',
          dataIndex: 'schedulable',
          width: 150,
          render: (schedulable: boolean, account) => (
            <Space size={4} wrap>
              <HealthBadge style={accountSchedulableStyle(schedulable)} />
              {account.automatic_pause && <Tag color="purple">自动暂停</Tag>}
            </Space>
          ),
        },
        {
          title: '标记特征',
          key: 'flags',
          render: (_, account) => {
            const flags = [
              account.expired && '已过期',
              account.temporary_unavailable && '临时不可用',
              account.group_ids.length > 1 && `共享 ${account.group_ids.length} 个分组`,
            ].filter((flag): flag is string => Boolean(flag))
            return flags.length === 0 ? (
              <Typography.Text type="secondary">—</Typography.Text>
            ) : (
              <Space size={4} wrap>
                {flags.map((flag) => (
                  <Tag key={flag}>{flag}</Tag>
                ))}
              </Space>
            )
          },
        },
        {
          title: '最近观测时间',
          dataIndex: 'observed_at',
          width: 180,
          render: (value: string | null) => (
            <Typography.Text type="secondary">
              {value ? dateTime.format(new Date(value)) : '—'}
            </Typography.Text>
          ),
        },
      ]}
    />
  )
}
