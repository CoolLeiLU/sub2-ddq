import { Card, Col, Flex, Row, Statistic } from 'antd'
import {
  ApiOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClusterOutlined,
  ControlOutlined,
} from '@ant-design/icons'

import type { Overview } from '../../api'
import { palette } from '../../theme'

interface Props {
  overview: Overview | null
}

export default function OverviewStats({ overview }: Props) {
  const enabled = Boolean(overview?.enabled)

  const items = [
    {
      title: '调度引擎状态',
      value: enabled ? '运行中' : '已停止',
      icon: enabled ? (
        <CheckCircleOutlined style={{ fontSize: 24, color: '#16a34a' }} />
      ) : (
        <CloseCircleOutlined style={{ fontSize: 24, color: palette.textTertiary }} />
      ),
      color: enabled ? '#16a34a' : palette.textTertiary,
    },
    {
      title: '纳管渠道总数',
      value: overview?.channel_count ?? 0,
      icon: <ApiOutlined style={{ fontSize: 24, color: palette.primary }} />,
      color: palette.text,
    },
    {
      title: '分组拓扑数',
      value: overview?.group_count ?? 0,
      icon: <ClusterOutlined style={{ fontSize: 24, color: palette.secondary }} />,
      color: palette.text,
    },
    {
      title: '当前策略版本',
      value: overview?.policy_revision ? `v${overview.policy_revision}` : 'v0',
      icon: <ControlOutlined style={{ fontSize: 24, color: palette.accent }} />,
      color: palette.text,
    },
  ]

  return (
    <Row gutter={[16, 16]}>
      {items.map((item) => (
        <Col xs={24} sm={12} lg={6} key={item.title}>
          <Card bordered={false} style={{ borderRadius: 8 }}>
            <Flex justify="space-between" align="center">
              <Statistic
                title={item.title}
                value={item.value}
                valueStyle={{ color: item.color, fontWeight: 600, fontSize: 24 }}
              />
              <Flex
                align="center"
                justify="center"
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 12,
                  background: '#f8fafc',
                }}
              >
                {item.icon}
              </Flex>
            </Flex>
          </Card>
        </Col>
      ))}
    </Row>
  )
}
