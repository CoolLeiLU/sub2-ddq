import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Popconfirm,
  Space,
  Spin,
  Switch,
  Typography,
  message,
} from 'antd'
import { PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'

import { ApiError, api, type Policy as PolicyModel } from '../api'
import { palette } from '../theme'

function newKey(): string {
  return `console-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const HIDDEN_KEYS = new Set(['enabled', 'revision'])

/** Current Guardian policy, plus the scheduling start/stop controls. */
export default function Policy() {
  const [policy, setPolicy] = useState<PolicyModel | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = () => {
    setLoading(true)
    api
      .policy()
      .then(setPolicy)
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const toggleEnabled = async (enabled: boolean) => {
    if (policy === null) return
    setBusy(true)
    try {
      const updated = await api.updatePolicy({ enabled }, policy.revision)
      setPolicy(updated)
      message.success(enabled ? '已启用 Guardian' : '已停用 Guardian')
    } catch (failure) {
      const detail = failure instanceof ApiError ? failure.message : '更新失败'
      message.error(detail)
      load()
    } finally {
      setBusy(false)
    }
  }

  const controlScheduling = async (start: boolean) => {
    setBusy(true)
    try {
      if (start) {
        await api.startScheduling(true, newKey())
        message.success('已启动调度')
      } else {
        await api.stopScheduling(true, newKey())
        message.success('已停止调度')
      }
      load()
    } catch (failure) {
      const detail = failure instanceof ApiError ? failure.message : '操作失败'
      message.error(detail)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Spin />
  if (error) return <Alert type="error" message={error} showIcon />

  const enabled = Boolean(policy?.enabled)
  const extraEntries = policy
    ? Object.entries(policy).filter(([key]) => !HIDDEN_KEYS.has(key))
    : []

  return (
    <>
      <Card title="调度控制" style={{ marginBottom: 'var(--space-xl)' }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 'var(--space-xl)' }}>
          启停 Guardian 的后台扫描与调度。停止后不再发起探测或账号恢复，但 API 仍可访问。
        </Typography.Paragraph>
        <Space size="middle">
          <Popconfirm
            title="启动调度"
            description="Guardian 将开始扫描并可能对上游发起写操作。确认启动？"
            okText="确认启动"
            cancelText="取消"
            onConfirm={() => controlScheduling(true)}
          >
            <Button type="primary" icon={<PlayCircleOutlined aria-hidden />} loading={busy}>
              启动调度
            </Button>
          </Popconfirm>
          <Popconfirm
            title="停止调度"
            description="Guardian 将停止探测与账号恢复。确认停止？"
            okText="确认停止"
            cancelText="取消"
            onConfirm={() => controlScheduling(false)}
          >
            <Button danger icon={<PauseCircleOutlined aria-hidden />} loading={busy}>
              停止调度
            </Button>
          </Popconfirm>
        </Space>
      </Card>

      <Card title="策略">
        {policy === null ? (
          <Typography.Text type="secondary">无策略</Typography.Text>
        ) : (
          <>
            <Descriptions column={{ xs: 1, sm: 2 }} size="small" style={{ marginBottom: 'var(--space-xl)' }}>
              <Descriptions.Item label="版本">
                <Typography.Text code>修订 {policy.revision}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="启用">
                <Space size="small">
                  <Switch checked={enabled} loading={busy} onChange={toggleEnabled} />
                  <Typography.Text type={enabled ? 'success' : 'secondary'}>
                    {enabled ? '已启用' : '已停用'}
                  </Typography.Text>
                </Space>
              </Descriptions.Item>
            </Descriptions>

            {extraEntries.length === 0 ? (
              <Typography.Text type="secondary">没有其他策略字段</Typography.Text>
            ) : (
              <Descriptions
                column={1}
                size="small"
                bordered
                title="其他字段"
                labelStyle={{
                  background: palette.background,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  width: 220,
                }}
              >
                {extraEntries.map(([key, value]) => (
                  <Descriptions.Item key={key} label={key}>
                    <Typography.Text
                      code
                      className="wrap-anywhere"
                      style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}
                    >
                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </Typography.Text>
                  </Descriptions.Item>
                ))}
              </Descriptions>
            )}
          </>
        )}
      </Card>
    </>
  )
}
