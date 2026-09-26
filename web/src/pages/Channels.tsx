import { useCallback, useEffect, useState } from 'react'
import { App } from 'antd'

import { api, type Channel, type Group } from '../api'
import PageContainer from '../components/common/PageContainer'
import PageError from '../components/common/PageError'
import ChannelFilterBar from '../components/channels/ChannelFilterBar'
import ChannelTable from '../components/channels/ChannelTable'

/**
 * Channels inventory page: lists all managed channels with their scores,
 * health status, latency and desired schedulable states.
 */
export default function Channels() {
  const { message } = App.useApp()
  const [channels, setChannels] = useState<Channel[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [groupId, setGroupId] = useState<string>('')

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .channels()
      .then((page) => setChannels(page.items))
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  useEffect(() => {
    api
      .groups()
      .then((page) => setGroups(page.items ?? []))
      .catch(() => setGroups([]))
  }, [])

  // Excluding a channel changes what Guardian schedules, so the list is
  // re-read afterwards rather than patched locally: the server derives health
  // and desired state from the action.
  const runAction = useCallback(
    async (channel: Channel, action: 'exclude' | 'include', key: string) => {
      try {
        await api.channelAction(channel.channel_id, action, key)
        message.success(action === 'exclude' ? '已排除该渠道' : '已恢复该渠道调度')
      } catch (failure) {
        message.error(failure instanceof Error ? failure.message : '操作失败')
      } finally {
        load()
      }
    },
    [load, message],
  )

  if (error) return <PageError message={error} onRetry={load} />

  const filtered = channels.filter((ch) => {
    if (groupId && ch.group_id !== groupId) return false
    const needle = query.trim().toLowerCase()
    if (!needle) return true
    return (
      ch.name.toLowerCase().includes(needle) ||
      ch.channel_id.includes(needle) ||
      ch.health.toLowerCase().includes(needle)
    )
  })

  return (
    <PageContainer
      title="渠道调度管理"
      subTitle="管理渠道资产健康评分、熔断机制及上下线期望状态"
      extra={
        <ChannelFilterBar
          groups={groups}
          selectedGroup={groupId}
          onGroupChange={setGroupId}
          searchQuery={query}
          onSearchChange={setQuery}
          onRefresh={load}
          loading={loading}
        />
      }
    >
      <ChannelTable channels={filtered} loading={loading} onAction={runAction} />
    </PageContainer>
  )
}
