import { useEffect, useState } from 'react'
import { Alert, Card, Col, Descriptions, Row, Spin, Statistic, Tag, Typography } from 'antd'

import { api, type Overview } from '../api'

const HEALTH_COLORS: Record<string, string> = {
  HEALTHY: 'green',
  DEGRADED: 'orange',
  FUSED: 'red',
  STALE: 'default',
  WARMING_UP: 'blue',
  EXCLUDED: 'default',
  MANUALLY_PAUSED: 'purple',
  PENDING: 'default',
}

/** Fleet summary: policy state, channel health distribution, last run. */
export default function Dashboard() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .overview()
      .then(setOverview)
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin />
  if (error) return <Alert type="error" message={error} showIcon />

  const counts = overview?.health_counts ?? {}
  const last = overview?.last_run ?? null

  return (
    <>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="调度状态"
              value={overview?.enabled ? '已启用' : '已停止'}
              valueStyle={{ color: overview?.enabled ? '#16a34a' : '#dc2626' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="渠道" value={overview?.channel_count ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="分组" value={overview?.group_count ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="策略版本" value={overview?.policy_revision ?? 0} />
          </Card>
        </Col>
      </Row>

      <Card title="渠道健康分布" style={{ marginTop: 16 }}>
        {Object.keys(counts).length === 0 ? (
          <Typography.Text type="secondary">暂无数据</Typography.Text>
        ) : (
          Object.entries(counts).map(([health, count]) => (
            <Tag key={health} color={HEALTH_COLORS[health] ?? 'default'} style={{ marginBottom: 8 }}>
              {health}：{count}
            </Tag>
          ))
        )}
      </Card>

      <Card title="最近一次运行" style={{ marginTop: 16 }}>
        {last === null ? (
          <Typography.Text type="secondary">尚未运行</Typography.Text>
        ) : (
          <Descriptions column={{ xs: 1, sm: 2 }} size="small">
            <Descriptions.Item label="状态">
              <Tag color={last.status === 'SUCCEEDED' ? 'green' : 'red'}>{last.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="开始时间">
              {new Date(last.started_at).toLocaleString('zh-CN')}
            </Descriptions.Item>
            <Descriptions.Item label="结束时间">
              {last.finished_at ? new Date(last.finished_at).toLocaleString('zh-CN') : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="运行 ID">{last.run_id.slice(0, 8)}</Descriptions.Item>
            {last.error_message && (
              <Descriptions.Item label="错误" span={2}>
                {last.error_code}：{last.error_message}
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Card>
    </>
  )
}
