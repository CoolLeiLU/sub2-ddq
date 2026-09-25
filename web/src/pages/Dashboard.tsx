import { useEffect, useState } from 'react'
import { Alert, Card, Col, Descriptions, Row, Spin, Statistic, Tag, Typography } from 'antd'

import StatusTag from '../components/StatusTag'
import { api, type Overview } from '../api'
import { healthStyle, palette, runStyle } from '../theme'

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
  const enabled = Boolean(overview?.enabled)

  return (
    <>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="调度状态"
              value={enabled ? '已启用' : '已停止'}
              valueStyle={{ color: enabled ? palette.primary : palette.textTertiary }}
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

      <Card title="渠道健康分布" style={{ marginTop: 'var(--space-xl)' }}>
        {Object.keys(counts).length === 0 ? (
          <Typography.Text type="secondary">暂无数据</Typography.Text>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-md)' }}>
            {Object.entries(counts).map(([health, count]) => (
              <Tag key={health} color="default" style={{ marginInlineEnd: 0, paddingInline: 10 }}>
                <span
                  aria-hidden
                  style={{
                    display: 'inline-block',
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: palette.textTertiary,
                    marginInlineEnd: 6,
                    verticalAlign: 'middle',
                  }}
                />
                {healthStyle(health).label}
                <span style={{ marginInlineStart: 8, fontFamily: 'var(--font-mono)' }}>{count}</span>
              </Tag>
            ))}
          </div>
        )}
      </Card>

      <Card title="最近一次运行" style={{ marginTop: 'var(--space-xl)' }}>
        {last === null ? (
          <Typography.Text type="secondary">尚未运行</Typography.Text>
        ) : (
          <Descriptions column={{ xs: 1, sm: 2 }} size="small">
            <Descriptions.Item label="状态">
              <StatusTag style={runStyle(last.status)} />
            </Descriptions.Item>
            <Descriptions.Item label="开始时间">
              {new Date(last.started_at).toLocaleString('zh-CN')}
            </Descriptions.Item>
            <Descriptions.Item label="结束时间">
              {last.finished_at ? new Date(last.finished_at).toLocaleString('zh-CN') : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="运行 ID">
              <Typography.Text code>{last.run_id.slice(0, 8)}</Typography.Text>
            </Descriptions.Item>
            {last.error_message && (
              <Descriptions.Item label="错误" span={2}>
                <Typography.Text type="danger" className="wrap-anywhere">
                  {last.error_code}：{last.error_message}
                </Typography.Text>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Card>
    </>
  )
}
