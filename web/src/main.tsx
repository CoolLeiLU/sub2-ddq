import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App as AntApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import 'antd/dist/reset.css'

import Console from './Console'

// The console is mounted under /guardian/, so the router is based there too.
const base = document.querySelector('base')?.getAttribute('href') || '/guardian/'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: { colorPrimary: '#2563eb', borderRadius: 8 },
      }}
    >
      <AntApp>
        <BrowserRouter basename={base}>
          <Console />
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
)
