import { Button, Flex, Layout, Space, Tag, Typography } from 'antd'
import {
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons'

import { palette } from '../../theme'

interface Props {
  username: string
  onLogout: () => void
}

/** Top navigation header with system status and operator actions. */
export default function AppHeader({ username, onLogout }: Props) {
  return (
    <Layout.Header
      style={{
        background: palette.surface,
        borderBlockEnd: `1px solid ${palette.border}`,
        paddingInline: 24,
        height: 56,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        zIndex: 1,
      }}
    >
      <Flex align="center" gap={12}>
        <Typography.Text strong style={{ fontSize: 16 }}>
          SUB2API 调度控制台
        </Typography.Text>
        <Tag color="blue" style={{ margin: 0, fontSize: 12 }}>
          v1.0
        </Tag>
      </Flex>

      <Space size={16} align="center">
        <Flex align="center" gap={6}>
          <UserOutlined style={{ color: palette.textSecondary }} />
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {username}
          </Typography.Text>
        </Flex>

        <Button
          type="text"
          danger
          size="small"
          icon={<LogoutOutlined />}
          onClick={onLogout}
        >
          退出
        </Button>
      </Space>
    </Layout.Header>
  )
}
