import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { LockOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons'

import { ApiError, api } from './api'

interface Props {
  onSignedIn: (username: string) => void
}

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
          failure.code === 'INVALID_CREDENTIALS'
            ? '用户名或密码不正确'
            : failure.message,
        )
      } else {
        setError('无法连接到 Guardian 服务')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #eef2ff 0%, #f8fafc 55%, #e0f2fe 100%)',
        padding: 24,
      }}
    >
      <Card style={{ width: 400, boxShadow: '0 12px 40px rgba(15, 23, 42, 0.08)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <SafetyOutlined style={{ fontSize: 40, color: '#2563eb' }} />
          <Typography.Title level={3} style={{ marginTop: 12, marginBottom: 4 }}>
            Guardian 调度控制台
          </Typography.Title>
          <Typography.Text type="secondary">
            监控渠道健康、执行有界调度，并统一处理异常账号恢复
          </Typography.Text>
        </div>

        {error && (
          <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />
        )}

        <Form layout="vertical" onFinish={submit} requiredMark={false} autoComplete="off">
          <Form.Item
            name="username"
            label="用户名"
            initialValue="admin"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="admin" size="large" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={submitting}>
            登录
          </Button>
        </Form>

        <Typography.Paragraph
          type="secondary"
          style={{ marginTop: 16, marginBottom: 0, fontSize: 12, textAlign: 'center' }}
        >
          登录状态保存在加密签名的 Cookie 中，密码仅以哈希形式存储。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
