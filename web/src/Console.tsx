import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Layout, Menu, Spin, Typography } from 'antd'
import {
  ApiOutlined,
  ClusterOutlined,
  DashboardOutlined,
  FileTextOutlined,
  LogoutOutlined,
  SettingOutlined,
} from '@ant-design/icons'

import { api } from './api'
import Login from './Login'
import Dashboard from './pages/Dashboard'
import Channels from './pages/Channels'
import Groups from './pages/Groups'
import Events from './pages/Events'
import Policy from './pages/Policy'

const { Header, Sider, Content } = Layout

const NAV = [
  { key: '/', icon: <DashboardOutlined />, label: '总览' },
  { key: '/channels', icon: <ApiOutlined />, label: '渠道' },
  { key: '/groups', icon: <ClusterOutlined />, label: '分组' },
  { key: '/events', icon: <FileTextOutlined />, label: '事件日志' },
  { key: '/policy', icon: <SettingOutlined />, label: '策略' },
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
      <Sider theme="light" breakpoint="lg" collapsedWidth={64} style={{ borderRight: '1px solid #f0f0f0' }}>
        <div style={{ padding: '20px 16px', fontWeight: 600, fontSize: 16 }}>
          <span style={{ color: '#2563eb' }}>Guardian</span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={NAV}
          onClick={({ key }) => {
            window.history.pushState({}, '', `/guardian${key === '/' ? '/' : key}`)
            window.dispatchEvent(new PopStateEvent('popstate'))
          }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            borderBottom: '1px solid #f0f0f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingInline: 24,
          }}
        >
          <Typography.Text strong>SUB2API 调度控制台</Typography.Text>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Typography.Text type="secondary">{username}</Typography.Text>
            <a onClick={signOut} style={{ cursor: 'pointer' }}>
              <LogoutOutlined /> 退出
            </a>
          </div>
        </Header>
        <Content style={{ padding: 24 }}>
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
