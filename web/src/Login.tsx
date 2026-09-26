import { useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Divider,
  Flex,
  Form,
  Input,
  Space,
  Tag,
  Typography,
} from 'antd'
import {
  CheckCircleFilled,
  LockOutlined,
  SafetyCertificateFilled,
  UserOutlined,
} from '@ant-design/icons'

import { ApiError, api } from './api'
import { palette } from './theme'

interface Props {
  onSignedIn: (username: string) => void
}

const HIGHLIGHTS = [
  '渠道健康评分与动态调度',
  '异常账号有界自动恢复',
  '慢首字守护与配额熔断',
  '全量操作审计与策略管控',
]

/**
 * Modern Ant Design Pro style console sign-in page.
 * Uses 100% Ant Design native layout and components without hand-written CSS classes.
 */
export default function Login({ onSignedIn }: Props) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (values: { username: string; password: string }) => {
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.login(values.username, values.password)
      onSignedIn(result.username)
    } catch (failure) {
      if (failure instanceof ApiError) {
        setError(
          failure.code === 'INVALID_CREDENTIALS' ? '用户名或密码不正确' : failure.message,
        )
      } else {
        setError('无法连接到 Guardian 后端服务')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Flex
      vertical
      justify="center"
      align="center"
      style={{
        minHeight: '100vh',
        background: 'linear-gradient(180deg, #f0f5ff 0%, #f8fafc 100%)',
        padding: '32px 16px',
      }}
    >
      <div style={{ width: '100%', maxWidth: 440 }}>
        {/* Brand Header */}
        <Flex vertical align="center" gap={8} style={{ marginBottom: 32 }}>
          <Flex
            align="center"
            justify="center"
            style={{
              width: 52,
              height: 52,
              borderRadius: 16,
              background: palette.primary,
              boxShadow: '0 8px 16px rgba(30, 64, 175, 0.24)',
            }}
          >
            <SafetyCertificateFilled style={{ fontSize: 28, color: '#ffffff' }} />
          </Flex>
          <Typography.Title level={3} style={{ margin: 0, fontWeight: 600 }}>
            SUB2API Guardian
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 14 }}>
            企业级高可用渠道调度与状态守护平台
          </Typography.Text>
        </Flex>

        {/* Login Card */}
        <Card
          bordered={false}
          style={{
            boxShadow: '0 10px 30px 0 rgba(0, 0, 0, 0.06)',
            borderRadius: 12,
          }}
          styles={{
            body: { padding: '32px 28px' },
          }}
        >
          <Typography.Title level={5} style={{ marginTop: 0, marginBottom: 20 }}>
            管理员登录
          </Typography.Title>

          {error && (
            <Alert
              type="error"
              message={error}
              showIcon
              style={{ marginBottom: 20 }}
            />
          )}

          <Form
            layout="vertical"
            onFinish={submit}
            requiredMark={false}
            autoComplete="off"
            size="large"
          >
            <Form.Item
              name="username"
              label="用户名"
              rules={[{ required: true, message: '请输入管理员用户名' }]}
            >
              <Input
                prefix={<UserOutlined style={{ color: palette.textTertiary }} />}
                placeholder="请输入用户名"
                allowClear
              />
            </Form.Item>

            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入登录密码' }]}
            >
              <Input.Password
                prefix={<LockOutlined style={{ color: palette.textTertiary }} />}
                placeholder="请输入密码"
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 12, marginTop: 8 }}>
              <Button
                type="primary"
                htmlType="submit"
                size="large"
                block
                loading={submitting}
                style={{ height: 44, fontWeight: 500 }}
              >
                登 录
              </Button>
            </Form.Item>
          </Form>

          <Divider style={{ margin: '20px 0 16px' }} />

          {/* Capabilities Badges */}
          <Flex vertical gap={8}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              系统特性
            </Typography.Text>
            <Flex wrap="wrap" gap={6}>
              {HIGHLIGHTS.map((item) => (
                <Tag
                  key={item}
                  icon={<CheckCircleFilled style={{ color: palette.primary }} />}
                  style={{
                    padding: '3px 8px',
                    borderRadius: 4,
                    fontSize: 12,
                    background: '#f1f5f9',
                    border: 'none',
                    margin: 0,
                  }}
                >
                  {item}
                </Tag>
              ))}
            </Flex>
          </Flex>
        </Card>

        {/* Footer info */}
        <Flex vertical align="center" gap={4} style={{ marginTop: 24 }}>
          <Space split={<Divider type="vertical" />}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              HttpOnly Cookie 会话
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Scrypt 密码哈希保护
            </Typography.Text>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            SUB2API Guardian Scheduler Console
          </Typography.Text>
        </Flex>
      </div>
    </Flex>
  )
}
