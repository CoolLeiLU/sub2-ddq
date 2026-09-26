import React from 'react'
import { Card, Flex, Typography } from 'antd'

interface Props {
  title: string
  subTitle?: string
  extra?: React.ReactNode
  children: React.ReactNode
}

/**
 * Standard Ant Design page container wrapper.
 * Provides a consistent header with title, subtitle and action buttons,
 * followed by the page content.
 */
export default function PageContainer({ title, subTitle, extra, children }: Props) {
  return (
    <Flex vertical gap={20}>
      <Card
        bordered={false}
        styles={{
          body: {
            padding: '16px 24px',
            borderRadius: 8,
          },
        }}
      >
        <Flex justify="space-between" align="center" wrap="wrap" gap={12}>
          <Flex vertical gap={4}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {title}
            </Typography.Title>
            {subTitle && (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {subTitle}
              </Typography.Text>
            )}
          </Flex>
          {extra && <Flex align="center" gap={8}>{extra}</Flex>}
        </Flex>
      </Card>

      <div style={{ width: '100%' }}>{children}</div>
    </Flex>
  )
}
