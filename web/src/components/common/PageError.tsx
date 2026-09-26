import { Alert, Button, Flex } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

interface Props {
  message: string
  onRetry?: () => void
}

/** Prominent error banner with an optional retry button. */
export default function PageError({ message, onRetry }: Props) {
  return (
    <Flex vertical gap={16} align="center" style={{ width: '100%', margin: '48px 0' }}>
      <div style={{ maxWidth: 640, width: '100%' }}>
        <Alert
          type="error"
          message="数据加载失败"
          description={message}
          showIcon
          action={
            onRetry && (
              <Button size="small" type="primary" danger icon={<ReloadOutlined />} onClick={onRetry}>
                重试
              </Button>
            )
          }
        />
      </div>
    </Flex>
  )
}
