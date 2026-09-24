import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Spin, Switch, Typography, message } from 'antd'
import { PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'

import { ApiError, api, type Policy as PolicyModel } from '../api'

function newKey(): string {
  return `console-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

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

  return (
    <>
      <Card title="调度控制" style={{ marginBottom: 16 }}>
        <Typography.Paragraph type="secondary">
          启停 Guardian 的后台扫描与调度。停止后不再发起探测或账号恢复，但 API 仍可访问。
        </Typography.Paragraph>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={busy}
          onClick={() => controlScheduling(true)}
          style={{ marginRight: 8 }}
        >
          启动调度
        </Button>
        <Button danger icon={<PauseCircleOutlined />} loading={busy} onClick={() => controlScheduling(false)}>
          停止调度
        </Button>
      </Card>

      <Card title="策略">
        {policy === null ? (
          <Typography.Text type="secondary">无策略</Typography.Text>
        ) : (
          <Descriptions column={{ xs: 1, sm: 2 }} size="small">
            <Descriptions.Item label="版本">修订 {policy.revision}</Descriptions.Item>
            <Descriptions.Item label="启用">
              <Switch
                checked={Boolean(policy.enabled)}
                loading={busy}
                onChange={toggleEnabled}
              />
            </Descriptions.Item>
            {Object.entries(policy)
              .filter(([key]) => key !== 'enabled' && key !== 'revision')
              .map(([key, value]) => (
                <Descriptions.Item key={key} label={key} span={2}>
                  <Typography.Text code style={{ fontSize: 12 }}>
                    {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                  </Typography.Text>
                </Descriptions.Item>
              ))}
          </Descriptions>
        )}
      </Card>
    </>
  )
}
