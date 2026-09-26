import { Flex, Layout, Menu, Typography } from 'antd'
import {
  ApiOutlined,
  ClusterOutlined,
  DashboardOutlined,
  FileTextOutlined,
  SafetyOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'

import { palette } from '../../theme'

const NAV_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: '总览看板' },
  { key: '/channels', icon: <ApiOutlined />, label: '渠道调度' },
  { key: '/groups', icon: <ClusterOutlined />, label: '分组拓扑' },
  { key: '/events', icon: <FileTextOutlined />, label: '事件审计' },
  { key: '/policy', icon: <SettingOutlined />, label: '策略中心' },
]

/** Left navigation sidebar in Ant Design v5 layout pattern. */
export default function AppSider() {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <Layout.Sider
      theme="light"
      breakpoint="lg"
      collapsedWidth={64}
      width={220}
      style={{
        borderInlineEnd: `1px solid ${palette.border}`,
        boxShadow: '1px 0 2px 0 rgba(0, 0, 0, 0.03)',
      }}
    >
      <Flex
        align="center"
        gap={10}
        style={{
          height: 56,
          paddingInline: 20,
          borderBlockEnd: `1px solid ${palette.border}`,
        }}
      >
        <SafetyOutlined style={{ fontSize: 20, color: palette.primary }} />
        <Flex vertical>
          <Typography.Text strong style={{ fontSize: 15, color: palette.primary, lineHeight: 1.2 }}>
            Guardian
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 11, lineHeight: 1.1 }}>
            调度管控面
          </Typography.Text>
        </Flex>
      </Flex>

      <Menu
        mode="inline"
        selectedKeys={[location.pathname]}
        items={NAV_ITEMS}
        style={{
          borderInlineEnd: 'none',
          paddingBlockStart: 12,
          paddingInline: 8,
        }}
        onClick={({ key }) => navigate(key)}
      />
    </Layout.Sider>
  )
}
