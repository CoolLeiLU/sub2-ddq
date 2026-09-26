import { Alert, Card, Descriptions, Tag, Typography } from 'antd'

import { palette } from '../../theme'
import DataCell from '../common/DataCell'

interface FieldDoc {
  key: string
  label: string
  help: string
  format?: string
  relevantWhen?: (group: Record<string, unknown>) => boolean
}

const ACCOUNT_RECOVERY_FIELDS: FieldDoc[] = [
  { key: 'enabled', label: '启用账号恢复', help: '关闭后完全不做账号测试与启停。', format: 'bool' },
  {
    key: 'owner',
    label: '恢复归属',
    help: '由谁执行恢复：GUARDIAN 表示 Guardian 自主执行；SCHEDULER 表示交给调度器。',
  },
  {
    key: 'trigger',
    label: '恢复触发方式',
    help: 'CONDITIONAL 表示只在证据条件满足时触发，不做无条件轮询。',
  },
  {
    key: 'max_concurrency',
    label: '恢复并发上限',
    help: '同时处理的账号数量上限。',
  },
  {
    key: 'max_accounts_per_episode',
    label: '单次事件账号上限',
    help: '一次渠道故障最多连带检查多少账号；超出则整批放弃，避免故障放大。',
  },
  {
    key: 'retry_cooldown_seconds',
    label: '同账号重试冷却',
    help: '异常账号与每小时巡检路径下，同一账号测试后多久内不再重复测试；渠道故障路径改用探测间隔。',
    format: 'seconds',
  },
]

function formatValue(value: unknown, format?: string): string {
  if (format === 'bool') return value ? '是' : '否'
  if (format === 'seconds' && typeof value === 'number') return `${value} 秒`
  return value !== null && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')
}

interface Props {
  accountRecovery: Record<string, unknown>
}

export default function AccountRecoveryCard({ accountRecovery }: Props) {
  const isEnabled = accountRecovery.enabled !== false

  return (
    <Card
      title="账号级自愈恢复机制 (Account Recovery)"
      extra={<Tag color={isEnabled ? 'blue' : 'default'}>{isEnabled ? '已启用' : '已关闭'}</Tag>}
      bordered={false}
      style={{ borderRadius: 8 }}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="触发机制与链路"
        description="当上游监控探测到某渠道失败时，打开一条渠道故障事件，并对该渠道所属分组下的全部账号逐一发起真实账号测试（串行执行，一次一个账号）；测试通过的账号重新启用，异常的账号停用。同一账号在冷却期内不重复测试。"
      />

      <Descriptions
        column={{ xs: 1, sm: 2 }}
        size="small"
        bordered
        labelStyle={{ background: palette.background, width: 220 }}
      >
        {ACCOUNT_RECOVERY_FIELDS.map((field) => {
          const value = accountRecovery[field.key]
          return (
            <Descriptions.Item
              key={field.key}
              label={
                <div>
                  <Typography.Text strong>{field.label}</Typography.Text>
                  <Typography.Text type="secondary" style={{ display: 'block', fontSize: 11 }}>
                    {field.key}
                  </Typography.Text>
                </div>
              }
            >
              <DataCell>{formatValue(value, field.format)}</DataCell>
            </Descriptions.Item>
          )
        })}
      </Descriptions>
    </Card>
  )
}
