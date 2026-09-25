import { useState } from 'react'
import { Alert, Button, Form, Input, Typography } from 'antd'
import { LockOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons'

import { ApiError, api } from './api'

interface Props {
  onSignedIn: (username: string) => void
}

const CAPABILITIES = [
  '渠道健康评分与分组调度',
  '账户恢复的有界执行与回读校验',
  '慢首字守护与配额保护',
  '全量事件审计与策略版本管理',
]

/** Console sign-in: exchanges the admin password for a session cookie. */
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
        setError('无法连接到 Guardian 服务')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-shell">
        {/* Brand panel. Hidden below 768px, where the form takes the full width. */}
        <aside className="login-brand">
          <div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-lg)',
                marginBottom: 'var(--space-2xl)',
              }}
            >
              <SafetyOutlined style={{ fontSize: 28 }} aria-hidden />
              <span style={{ fontSize: 18, fontWeight: 600, letterSpacing: '0.01em' }}>
                Guardian
              </span>
            </div>
            <Typography.Title
              level={2}
              style={{ color: 'inherit', margin: 0, fontSize: 24, fontWeight: 600 }}
            >
              SUB2API 调度控制台
            </Typography.Title>
            <Typography.Paragraph
              style={{
                color: 'rgba(255, 255, 255, 0.78)',
                marginTop: 'var(--space-lg)',
                marginBottom: 0,
                fontSize: 14,
                lineHeight: 1.7,
              }}
            >
              面向运维的管理面：监控渠道健康、执行有界调度，并统一处理异常账号恢复。
            </Typography.Paragraph>
          </div>

          <ul className="login-capabilities">
            {CAPABILITIES.map((item) => (
              <li key={item}>
                <span className="login-capability-dot" aria-hidden />
                {item}
              </li>
            ))}
          </ul>
        </aside>

        {/* Form panel. */}
        <main className="login-form">
          <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 'var(--space-sm)' }}>
            登录
          </Typography.Title>
          <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>
            请输入管理员凭据以继续
          </Typography.Text>

          {error && (
            <Alert
              type="error"
              message={error}
              showIcon
              style={{ marginBottom: 'var(--space-xl)' }}
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
              initialValue="admin"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input prefix={<UserOutlined aria-hidden />} placeholder="admin" />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password prefix={<LockOutlined aria-hidden />} placeholder="密码" />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              loading={submitting}
              style={{ marginTop: 'var(--space-sm)' }}
            >
              登录
            </Button>
          </Form>

          <Typography.Paragraph
            type="secondary"
            style={{
              marginTop: 'var(--space-2xl)',
              marginBottom: 0,
              fontSize: 12,
              lineHeight: 1.7,
            }}
          >
            登录状态保存在加密签名的 Cookie 中，密码仅以哈希形式存储。
          </Typography.Paragraph>
        </main>
      </div>
    </div>
  )
}
