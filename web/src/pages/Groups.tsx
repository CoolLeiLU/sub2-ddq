import { useCallback, useEffect, useState } from 'react'
import { Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { api, type Group } from '../api'
import PageContainer from '../components/common/PageContainer'
import PageError from '../components/common/PageError'
import GroupTable from '../components/groups/GroupTable'

/**
 * Groups topology page: displays group health scores and accounts managed
 * under each group.
 */
export default function Groups() {
  const [groups, setGroups] = useState<Group[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .groups()
      .then((page) => setGroups(page.items ?? []))
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  if (error) return <PageError message={error} onRetry={load} />

  return (
    <PageContainer
      title="分组拓扑管理"
      subTitle="查看各业务分组的健康度评分及分组内账号的生命周期状态"
      extra={
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          刷新
        </Button>
      }
    >
      <GroupTable groups={groups} loading={loading} />
    </PageContainer>
  )
}
