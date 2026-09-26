import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from 'antd'

import { api } from './api'
import Login from './Login'
import PageLoading from './components/PageLoading'
import AppSider from './components/AppSider'
import AppHeader from './components/AppHeader'
import Dashboard from './pages/Dashboard'
import Channels from './pages/Channels'
import Groups from './pages/Groups'
import Events from './pages/Events'
import Policy from './pages/Policy'

export default function Console() {
  const [checking, setChecking] = useState(true)
  const [username, setUsername] = useState<string | null>(null)

  // Probe existing session so a refresh keeps the operator signed in.
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

  const handleLogout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUsername(null)
    }
  }, [])

  if (checking) {
    return <PageLoading tip="正在检查登录状态…" />
  }

  if (username === null) {
    return <Login onSignedIn={setUsername} />
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <AppSider />
      <Layout>
        <AppHeader username={username} onLogout={handleLogout} />
        <Layout.Content style={{ padding: 24 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/channels" element={<Channels />} />
            <Route path="/groups" element={<Groups />} />
            <Route path="/events" element={<Events />} />
            <Route path="/policy" element={<Policy />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
