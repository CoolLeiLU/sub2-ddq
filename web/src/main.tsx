import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import 'antd/dist/reset.css'

import Console from './Console'
import { themeConfig } from './theme'
import './styles/antd.css'
import './styles/theme.css'

// The console is mounted under /guardian/. The path is stated here rather than
// read from a <base> tag: the CSP sets `base-uri 'none'`, which makes any
// <base> element inert, and Vite already emits absolute asset URLs.
const base = '/guardian/'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={themeConfig}>
      <AntApp>
        <BrowserRouter basename={base}>
          <Console />
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
)
