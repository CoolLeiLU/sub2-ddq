import { useCallback, useEffect, useState } from 'react'
import { Button, Flex } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { api, type Overview } from '../api'
import PageContainer from '../components/common/PageContainer'
import PageLoading from '../components/common/PageLoading'
import PageError from '../components/common/PageError'
import OverviewStats from '../components/dashboard/OverviewStats'
import HealthDistribution from '../components/dashboard/HealthDistribution'
import LastRunStatus from '../components/dashboard/LastRunStatus'

/**
 * Dashboard page: displays overview KPI metrics, channel health distribution,
 * and the latest scheduling run details.
 */
export default function Dashboard() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .overview()
      .then(setOverview)
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  if (loading) return <PageLoading tip="正在加载系统状态总览…" />
  if (error) return <PageError message={error} onRetry={load} />

  const counts = overview?.health_counts ?? {}
  const last = overview?.last_run ?? null

  return (
    <PageContainer
      title="总览看板"
      subTitle="实时监控集群健康评分、调度引擎运行状态及最近执行轮次"
      extra={
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
      }
    >
      <Flex vertical gap={16}>
        <OverviewStats overview={overview} />
        <HealthDistribution counts={counts} />
        <LastRunStatus lastRun={last} />
      </Flex>
    </PageContainer>
  )
}
