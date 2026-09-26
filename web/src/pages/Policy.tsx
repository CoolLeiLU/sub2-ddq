import { useCallback, useEffect, useState } from 'react'
import { App, Flex } from 'antd'

import { ApiError, api, type Policy as PolicyModel } from '../api'
import PageContainer from '../components/common/PageContainer'
import PageLoading from '../components/common/PageLoading'
import PageError from '../components/common/PageError'
import SchedulingControlCard from '../components/policy/SchedulingControlCard'
import AccountRecoveryCard from '../components/policy/AccountRecoveryCard'
import PolicyGroupCollapse, { type GroupDoc } from '../components/policy/PolicyGroupCollapse'

function newKey(): string {
  return `console-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const POLICY_GROUPS: GroupDoc[] = [
  {
    key: 'scope',
    title: '管理范围 (Scope)',
    intent: '决定 Guardian 接管哪些分组和渠道；范围之外的一切都不被评估、不被写入。',
    fields: [
      { key: 'managed_group_mode', label: '分组范围模式', help: 'all 表示接管所有分组；selected 表示只接管“管理分组”清单内的分组。' },
      { key: 'managed_group_ids', label: '管理分组清单', help: '模式为 selected 时生效，只有清单内的分组参与调度。', format: 'list' },
      { key: 'excluded_group_ids', label: '排除分组', help: '无论模式如何都跳过这些分组，其渠道保持上游原状。', format: 'list' },
      { key: 'managed_account_types', label: '管理账号类型', help: '账号恢复只处理这些类型的账号；留空表示不限类型。', format: 'list' },
      { key: 'managed_platforms', label: '管理平台', help: '按平台限定纳管渠道；留空表示不限平台。', format: 'list' },
      { key: 'paused_channel_ids', label: '人工暂停渠道', help: '这些渠道保持不可调度，但仍会被探测，等待人工恢复。', format: 'list' },
      { key: 'excluded_channel_ids', label: '排除渠道', help: '完全退出 Guardian 管理，既不调度也不探测。', format: 'list' },
    ],
  },
  {
    key: 'scoring',
    title: '评分与采样窗口 (Scoring)',
    intent:
      '把每个渠道的观测事件折算成 0–100 的健康分。健康分只作为熔断/降级/恢复的判据，不参与排序，也不分配任何权重。',
    fields: [
      { key: 'short_window', label: '短期事件窗口', help: '短期分数取的最近样本条数。' },
      { key: 'long_window', label: '长期事件窗口', help: '长期分数取的最大样本条数。' },
      {
        key: 'latest_weight',
        label: '最新观测占比',
        help: '算短期分时，最新一条观测占的比重；越大越敏感。仅影响分值本身。',
      },
      { key: 'short_ratio', label: '短期分占比', help: '最终分 = 短期分 × 该比例 + 长期分 ×（1 − 该比例）。' },
      { key: 'decay', label: '历史衰减', help: '算分时旧样本的衰减系数，越小越快遗忘历史观测。' },
      { key: 'short_window_minutes', label: '短期时间窗', help: '短期分只统计该时长内的观测。', format: 'seconds' },
      { key: 'long_window_minutes', label: '长期时间窗', help: '长期分统计该时长内的观测。', format: 'seconds' },
      { key: 'slow_ttfb_ms', label: '慢响应阈值', help: '首字节超过该毫秒数即记为“响应偏慢”事件。' },
    ],
  },
  {
    key: 'breaker',
    title: '熔断策略 (Circuit Breaker)',
    intent: '在证据足够时把持续失败的渠道标记为熔断、停止调度，避免把流量持续打到故障渠道。',
    fields: [
      { key: 'enabled', label: '启用熔断', help: '关闭后渠道不会因失败被自动摘出。', format: 'bool' },
      { key: 'http_failures', label: '触发熔断的错误数', help: '窗口内失败事件达到该数量即熔断。' },
      { key: 'http_score_below', label: '熔断分数上限', help: '健康分低于该值时熔断才生效，避免误杀。' },
      { key: 'latency_ttfb_ms', label: '延迟熔断阈值', help: '首字节超过该毫秒数算一次慢响应。' },
      { key: 'fused_cooldown_seconds', label: '熔断冷却期', help: '熔断后至少等待该时长才考虑恢复。', format: 'seconds' },
      { key: 'min_pool_size', label: '分组最小可用数', help: '分组可用渠道≤该值时不再熔断，改为“保留”以免整组不可用。' },
      { key: 'hard_fatal', label: '致命错误立即熔断', help: '确认致命错误时跳过窗口统计直接处理。', format: 'bool' },
    ],
  },
  {
    key: 'recovery',
    title: '自愈恢复 (Recovery)',
    intent: '熔断渠道在满足打分和连续成功次数并维持观察期后，自动恢复调度。',
    fields: [
      { key: 'enabled', label: '启用自动恢复', help: '关闭后熔断渠道只能人工恢复。', format: 'bool' },
      { key: 'probe_interval_seconds', label: '恢复探测间隔', help: '熔断期间多久探测一次该渠道。', format: 'seconds' },
      { key: 'target_score', label: '恢复目标分', help: '健康分达到该值才允许恢复。' },
      { key: 'success_count', label: '连续成功次数', help: '需要连续成功多少次观测才判定恢复。' },
      { key: 'hold_seconds', label: '恢复观察期', help: '达标后还需稳定保持该时长才真正恢复调度。', format: 'seconds' },
    ],
  },
  {
    key: 'probe',
    title: '主动探测 (Probing)',
    intent: '定期对渠道发起真实请求，作为独立于真实流量的健康证据；探测间隔同时决定熔断渠道的恢复尝试节奏。',
    fields: [
      { key: 'enabled', label: '启用主动探测', help: '关闭后不再对渠道发起主动探测，仅依赖真实流量证据。', format: 'bool' },
      { key: 'interval_seconds', label: '探测间隔', help: '两次主动探测之间的间隔，也是异常账号在巡检路径下的重试节奏。', format: 'seconds' },
      { key: 'timeout_seconds', label: '探测超时', help: '单次探测超过该时长记为失败。', format: 'seconds' },
      { key: 'concurrency', label: '探测并发', help: '同时进行的探测数量上限。' },
      { key: 'skip_when_traffic_fresh', label: '有实时流量时跳过', help: '该渠道近期有真实流量时跳过主动探测，节省额度。', format: 'bool' },
    ],
  },
]

export default function Policy() {
  const { message } = App.useApp()
  const [policy, setPolicy] = useState<PolicyModel | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .policy()
      .then(setPolicy)
      .catch((failure) => setError(failure.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const toggleEnabled = async (enabled: boolean) => {
    if (policy === null) return
    setBusy(true)
    try {
      const updated = await api.updatePolicy({ enabled }, policy.revision)
      setPolicy(updated)
      message.success(enabled ? '已开启 Guardian 策略自动执行' : '已停用 Guardian 策略')
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
        message.success('已启动自动调度')
      } else {
        await api.stopScheduling(true, newKey())
        message.success('已停止自动调度')
      }
      load()
    } catch (failure) {
      const detail = failure instanceof ApiError ? failure.message : '操作失败'
      message.error(detail)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <PageLoading tip="正在加载系统调度策略配置…" />
  if (error) return <PageError message={error} onRetry={load} />
  if (policy === null) return <PageError message="未获取到策略数据" onRetry={load} />

  const enabled = Boolean(policy.enabled)
  const accountRecovery = (policy.account_recovery ?? {}) as Record<string, unknown>

  return (
    <PageContainer
      title="调度策略控制中心"
      subTitle="定义系统管理范围、打分窗口、熔断阈值及账号自愈机制的全部核心参数"
    >
      <Flex vertical gap={16}>
        <SchedulingControlCard
          enabled={enabled}
          busy={busy}
          onToggleEnabled={toggleEnabled}
          onControlScheduling={controlScheduling}
        />

        <AccountRecoveryCard accountRecovery={accountRecovery} />

        <PolicyGroupCollapse
          groups={POLICY_GROUPS}
          policy={policy as unknown as Record<string, unknown>}
          revision={policy.revision}
        />
      </Flex>
    </PageContainer>
  )
}
