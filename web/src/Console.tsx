import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Button, Layout, Menu, Spin, Typography } from 'antd'
import {
  ApiOutlined,
  ClusterOutlined,
  DashboardOutlined,
  FileTextOutlined,
  LogoutOutlined,
  SafetyOutlined,
  SettingOutlined,
} from '@ant-design/icons'

import { api } from './api'
import Login from './Login'
import Dashboard from './pages/Dashboard'
import Channels from './pages/Channels'
import Groups from './pages/Groups'
import Events from './pages/Events'
import Policy from './pages/Policy'
import { palette } from './theme'

const { Header, Sider, Content } = Layout

const NAV = [
  { key: '/', icon: <DashboardOutlined aria-hidden />, label: '总览' },
  { key: '/channels', icon: <ApiOutlined aria-hidden />, label: '渠道' },
  { key: '/groups', icon: <ClusterOutlined aria-hidden />, label: '分组' },
  { key: '/events', icon: <FileTextOutlined aria-hidden />, label: '事件日志' },
  { key: '/policy', icon: <SettingOutlined aria-hidden />, label: '策略' },
]

export default function Console() {
  const [checking, setChecking] = useState(true)
  const [username, setUsername] = useState<string | null>(null)
  const location = useLocation()

  // Probe the existing session so a refresh keeps the operator signed in.
  useEffect(() => {
    let cancelled = false
    api
      .session()
      .then((info) => {
        if (!cancelled) setUsername(info.authenticated ? (info.username ?? 'admin') : null)
      })
      .catch(() => {
        if (!cancelled) setUsername(null)
      })
      .finally(() => {
        if (!cancelled) setChecking(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (checking) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <Spin size="large" tip="正在检查登录状态…" />
      </div>
    )
  }

  if (username === null) {
    return <Login onSignedIn={setUsername} />
  }

  const signOut = async () => {
    try {
      await api.logout()
    } finally {
      setUsername(null)
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        theme="light"
        breakpoint="lg"
        collapsedWidth={64}
        style={{ borderRight: `1px solid ${palette.border}` }}
      >
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-md)',
            padding: '0 16px',
            borderBottom: `1px solid ${palette.border}`,
          }}
        >
          <SafetyOutlined style={{ fontSize: 18, color: palette.primary }} aria-hidden />
          <span style={{ fontWeight: 600, fontSize: 15, color: palette.primary }}>Guardian</span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={NAV}
          style={{ borderInlineEnd: 'none', paddingTop: 'var(--space-md)' }}
          onClick={({ key }) => {
            window.history.pushState({}, '', `/guardian${key === '/' ? '/' : key}`)
            window.dispatchEvent(new PopStateEvent('popstate'))
          }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: palette.surface,
            borderBottom: `1px solid ${palette.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-xl)',
          }}
        >
          <Typography.Text strong style={{ fontSize: 15 }}>
            SUB2API 调度控制台
          </Typography.Text>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xl)' }}>
            <Typography.Text type="secondary">{username}</Typography.Text>
            <Button type="text" icon={<LogoutOutlined aria-hidden />} onClick={signOut}>
              退出
            </Button>
          </div>
        </Header>
        <Content style={{ padding: 'var(--space-2xl)' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/channels" element={<Channels />} />
            <Route path="/groups" element={<Groups />} />
            <Route path="/events" element={<Events />} />
            <Route path="/policy" element={<Policy />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}
