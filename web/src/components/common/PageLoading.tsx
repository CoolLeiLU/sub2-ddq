import { Flex, Spin } from 'antd'

/** Full-height centered spinner shown while a page fetches its initial data. */
export default function PageLoading({ tip = '正在加载数据…' }: { tip?: string }) {
  return (
    <Flex align="center" justify="center" style={{ minHeight: 360, width: '100%' }}>
      <Spin size="large" tip={tip}>
        <div style={{ padding: 60 }} />
      </Spin>
    </Flex>
  )
}
