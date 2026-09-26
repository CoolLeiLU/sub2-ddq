import { Button, Input, Select, Space } from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'

import type { Group } from '../../api'

interface Props {
  groups: Group[]
  selectedGroup: string
  onGroupChange: (groupId: string) => void
  searchQuery: string
  onSearchChange: (query: string) => void
  onRefresh: () => void
  loading?: boolean
}

export default function ChannelFilterBar({
  groups,
  selectedGroup,
  onGroupChange,
  searchQuery,
  onSearchChange,
  onRefresh,
  loading,
}: Props) {
  return (
    <Space wrap size="middle">
      <Select
        allowClear
        placeholder="全部业务分组"
        style={{ minWidth: 200 }}
        value={selectedGroup || undefined}
        onChange={(val) => onGroupChange(val ?? '')}
        options={groups.map((g) => ({
          value: g.group_id,
          label: g.name,
        }))}
      />

      <Input
        allowClear
        prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
        placeholder="按渠道名称、ID 或健康状态检索"
        style={{ width: 280 }}
        value={searchQuery}
        onChange={(e) => onSearchChange(e.target.value)}
      />

      <Button icon={<ReloadOutlined />} onClick={onRefresh} loading={loading}>
        刷新
      </Button>
    </Space>
  )
}
