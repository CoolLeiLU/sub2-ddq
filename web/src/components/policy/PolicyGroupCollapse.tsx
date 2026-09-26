import { Card, Collapse, Flex, Space, Table, Tag, Typography } from 'antd'

import DataCell from '../common/DataCell'

export interface FieldDoc {
  key: string
  label: string
  help: string
  format?: 'text' | 'seconds' | 'ratio' | 'percent' | 'list' | 'bool'
}

export interface GroupDoc {
  key: string
  title: string
  intent: string
  fields: FieldDoc[]
}

interface Props {
  groups: GroupDoc[]
  policy: Record<string, unknown>
  revision: number
}

function renderValue(value: unknown, format?: string): string {
  if (value === undefined || value === null) return '—'
  if (format === 'bool') return value ? '是' : '否'
  if (format === 'seconds' && typeof value === 'number') return `${value} 秒`
  if (format === 'percent' && typeof value === 'number') return `${Math.round(value * 100)}%`
  if (format === 'list' && Array.isArray(value)) return value.join('、') || '空'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export default function PolicyGroupCollapse({ groups, policy, revision }: Props) {
  const getGroupValue = (key: string): Record<string, unknown> => {
    const val = policy[key]
    return val !== null && typeof val === 'object' ? (val as Record<string, unknown>) : {}
  }

  return (
    <Card
      title="全量调度引擎策略定义"
      extra={<Tag color="processing">策略版本 rev.{revision}</Tag>}
      bordered={false}
      style={{ borderRadius: 8 }}
    >
      <Collapse
        defaultActiveKey={groups.map((g) => g.key)}
        items={groups.map((group) => {
          const groupVal = getGroupValue(group.key)
          const blockEnabled = typeof groupVal.enabled === 'boolean' ? groupVal.enabled : undefined

          const rows = group.fields.map((field) => ({
            key: field.key,
            label: field.label,
            help: field.help,
            value: renderValue(groupVal[field.key], field.format),
          }))

          return {
            key: group.key,
            label: (
              <Space size="small">
                <Typography.Text strong>{group.title}</Typography.Text>
                {blockEnabled !== undefined && (
                  <Tag color={blockEnabled ? 'blue' : 'default'}>
                    {blockEnabled ? '已启用' : '已关闭'}
                  </Tag>
                )}
              </Space>
            ),
            children: (
              <Flex vertical gap={12}>
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  {group.intent}
                </Typography.Text>
                <Table
                  size="small"
                  pagination={false}
                  rowKey="key"
                  dataSource={rows}
                  columns={[
                    {
                      title: '策略项',
                      dataIndex: 'label',
                      width: 220,
                      render: (label: string, row) => (
                        <div>
                          <Typography.Text>{label}</Typography.Text>
                          <Typography.Text
                            type="secondary"
                            style={{ display: 'block', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                          >
                            {row.key}
                          </Typography.Text>
                        </div>
                      ),
                    },
                    {
                      title: '当前配置参数',
                      dataIndex: 'value',
                      width: 260,
                      render: (val: string) => <DataCell>{val}</DataCell>,
                    },
                    {
                      title: '策略含义与生效机制',
                      dataIndex: 'help',
                      render: (text: string) => (
                        <Typography.Text type="secondary">{text}</Typography.Text>
                      ),
                    },
                  ]}
                />
              </Flex>
            ),
          }
        })}
      />
    </Card>
  )
}
