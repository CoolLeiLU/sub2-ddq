import { Button, Select, Space } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { severityStyle } from '../../theme'

interface Props {
  severity: string | undefined
  onSeverityChange: (severity: string | undefined) => void
  onRefresh: () => void
  loading?: boolean
}

const SEVERITY_LEVELS = ['INFO', 'WARNING', 'ERROR', 'CRITICAL']

export default function EventFilterBar({
  severity,
  onSeverityChange,
  onRefresh,
  loading,
}: Props) {
  return (
    <Space size="middle">
      <Select
        allowClear
        placeholder="全部日志级别"
        style={{ width: 160 }}
        value={severity}
        onChange={onSeverityChange}
        options={SEVERITY_LEVELS.map((v) => ({
          value: v,
          label: severityStyle(v).label,
        }))}
      />

      <Button icon={<ReloadOutlined />} onClick={onRefresh} loading={loading}>
        刷新
      </Button>
    </Space>
  )
}
