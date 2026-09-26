import { Button, Card, Flex, Popconfirm, Space, Switch, Typography } from 'antd'
import { PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'

interface Props {
  enabled: boolean
  busy: boolean
  onToggleEnabled: (enabled: boolean) => void
  onControlScheduling: (start: boolean) => void
}

export default function SchedulingControlCard({
  enabled,
  busy,
  onToggleEnabled,
  onControlScheduling,
}: Props) {
  return (
    <Card title="调度引擎控制面板" bordered={false} style={{ borderRadius: 8 }}>
      <Flex vertical gap={16}>
        <Flex justify="space-between" align="center" wrap="wrap" gap={12}>
          <div>
            <Typography.Text strong style={{ fontSize: 15, display: 'block' }}>
              后台自动化调度
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              控制 Guardian 后台扫描与渠道调度决策。停止后不发起探测或账号恢复，但 API 仍可正常读取。
            </Typography.Text>
          </div>

          <Space size="middle">
            <Popconfirm
              title="启动调度"
              description="Guardian 将开始周期性扫描并可能对上游发起调度决策写入。确认启动？"
              okText="确认启动"
              cancelText="取消"
              onConfirm={() => onControlScheduling(true)}
            >
              <Button type="primary" icon={<PlayCircleOutlined />} loading={busy}>
                启动调度
              </Button>
            </Popconfirm>

            <Popconfirm
              title="停止调度"
              description="Guardian 将立即停止自动探测与账号恢复流程。确认停止？"
              okText="确认停止"
              cancelText="取消"
              onConfirm={() => onControlScheduling(false)}
            >
              <Button danger icon={<PauseCircleOutlined />} loading={busy}>
                停止调度
              </Button>
            </Popconfirm>
          </Space>
        </Flex>

        <Flex
          align="center"
          gap={12}
          style={{
            padding: '12px 16px',
            background: '#f8fafc',
            borderRadius: 6,
            border: '1px solid #f1f5f9',
          }}
        >
          <Switch checked={enabled} loading={busy} onChange={onToggleEnabled} />
          <div>
            <Typography.Text strong style={{ fontSize: 14 }}>
              Guardian 策略执行总开关：
            </Typography.Text>
            <Typography.Text
              type={enabled ? 'success' : 'secondary'}
              style={{ marginLeft: 6, fontSize: 13 }}
            >
              {enabled ? '已开启（策略按预设规则自动生效）' : '已停用（保持被动模式，不执行任何写操作）'}
            </Typography.Text>
          </div>
        </Flex>
      </Flex>
    </Card>
  )
}
