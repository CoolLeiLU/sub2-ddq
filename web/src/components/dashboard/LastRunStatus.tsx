import { Card, Descriptions, Empty, Typography } from 'antd'

import type { RunSummary } from '../../api'
import { runStyle } from '../../theme'
import HealthBadge from '../common/HealthBadge'
import DataCell from '../common/DataCell'

interface Props {
  lastRun: RunSummary | null
}

export default function LastRunStatus({ lastRun }: Props) {
  return (
    <Card title="最近一次调度轮次" bordered={false} style={{ borderRadius: 8 }}>
      {lastRun === null ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未产生调度执行记录" />
      ) : (
        <Descriptions
          column={{ xs: 1, sm: 2, md: 4 }}
          size="middle"
          bordered={false}
        >
          <Descriptions.Item label="执行状态">
            <HealthBadge style={runStyle(lastRun.status)} />
          </Descriptions.Item>

          <Descriptions.Item label="执行 ID">
            <Typography.Text code copyable={{ text: lastRun.run_id }}>
              {lastRun.run_id.slice(0, 8)}
            </Typography.Text>
          </Descriptions.Item>

          <Descriptions.Item label="开始时间">
            <DataCell>{new Date(lastRun.started_at).toLocaleString('zh-CN')}</DataCell>
          </Descriptions.Item>

          <Descriptions.Item label="完成时间">
            <DataCell>
              {lastRun.finished_at ? new Date(lastRun.finished_at).toLocaleString('zh-CN') : '进行中…'}
            </DataCell>
          </Descriptions.Item>

          {lastRun.error_message && (
            <Descriptions.Item label="异常原因" span={4}>
              <Typography.Text type="danger" style={{ overflowWrap: 'anywhere' }}>
                [{lastRun.error_code}] {lastRun.error_message}
              </Typography.Text>
            </Descriptions.Item>
          )}
        </Descriptions>
      )}
    </Card>
  )
}
