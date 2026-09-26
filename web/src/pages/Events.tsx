import { useCallback, useEffect, useState } from 'react'

import { api, type GuardianEvent } from '../api'
import PageContainer from '../components/common/PageContainer'
import PageError from '../components/common/PageError'
import EventFilterBar from '../components/events/EventFilterBar'
import EventTable from '../components/events/EventTable'

/**
 * Events log page: audit trail for status switches, quarantine, and recovery actions.
 */
export default function Events() {
  const [events, setEvents] = useState<GuardianEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [severity, setSeverity] = useState<string | undefined>(undefined)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .events(100)
      .then((page) => setEvents(page.items ?? []))
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  if (error) return <PageError message={error} onRetry={load} />

  const filtered = severity ? events.filter((e) => e.severity === severity) : events

  return (
    <PageContainer
      title="事件审计日志"
      subTitle="全量追踪集群渠道熔断、降级、恢复以及策略变更的历史事件轨迹"
      extra={
        <EventFilterBar
          severity={severity}
          onSeverityChange={setSeverity}
          onRefresh={load}
          loading={loading}
        />
      }
    >
      <EventTable events={filtered} loading={loading} />
    </PageContainer>
  )
}
