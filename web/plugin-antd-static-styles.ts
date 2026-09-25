/**
 * Vite plugin that extracts antd's component styles into a static stylesheet.
 *
 * The console runs under `style-src 'self'`, which blocks the <style> tags
 * antd injects at runtime, leaving every component unstyled. Rendering the
 * components once with a shared cssinjs cache and serialising that cache gives
 * one CSS file that the normal stylesheet pipeline fingerprints and links, so
 * the CSP stays strict.
 *
 * The component list is explicit: pages fetch their data in effects, so an
 * app-level render would only style whatever happened to mount.
 *
 * The generated file is written into src/styles/ and imported by main.tsx; it
 * is a build artifact and is git-ignored.
 */
import { createCache, extractStyle, StyleProvider } from '@ant-design/cssinjs'
import { renderToString } from 'react-dom/server'
import React from 'react'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

import {
  Alert,
  App,
  Button,
  Card,
  Col,
  ConfigProvider,
  Descriptions,
  Form,
  Input,
  Layout,
  Menu,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import zhCN from 'antd/locale/zh_CN.js'

import { themeConfig } from './src/theme'
import StatusTag from './src/components/StatusTag'

const { Header, Sider, Content } = Layout

const columns = [
  {
    title: 'A',
    dataIndex: 'a',
    render: () =>
      React.createElement(StatusTag, { style: { tone: 'success', label: '健康' } }),
  },
  { title: 'B', dataIndex: 'b' },
]

/** One tree exercising every component, variant and size the console renders. */
function Showcase() {
  return React.createElement(
    Layout,
    null,
    React.createElement(
      Sider,
      { theme: 'light', breakpoint: 'lg', collapsedWidth: 64 },
      React.createElement(Menu, {
        mode: 'inline',
        selectedKeys: ['/'],
        items: [{ key: '/', label: '总览' }],
      }),
    ),
    React.createElement(
      Layout,
      null,
      React.createElement(Header, null, React.createElement(Typography.Text, null, 'Header')),
      React.createElement(
        Content,
        null,
        React.createElement(
          Row,
          { gutter: [16, 16] },
          React.createElement(
            Col,
            { span: 12 },
            React.createElement(Card, null, React.createElement(Statistic, { title: 'T', value: 1 })),
          ),
        ),
        React.createElement(
          Card,
          { title: 'Card', extra: React.createElement(Input.Search, { value: '', style: { width: 280 } }) },
          React.createElement(Alert, { type: 'error', message: 'e', showIcon: true }),
          React.createElement(Alert, { type: 'warning', message: 'w', showIcon: true }),
          React.createElement(Alert, { type: 'success', message: 's', showIcon: true }),
          React.createElement(Alert, { type: 'info', message: 'i', showIcon: true }),
          React.createElement(Spin, { size: 'large' }),
          React.createElement(Progress, { percent: 50, size: 'small' }),
          React.createElement(
            Space,
            null,
            React.createElement(Button, { type: 'primary', size: 'large' }, 'primary'),
            React.createElement(Button, { danger: true }, 'danger'),
            React.createElement(Button, { type: 'text' }, 'text'),
          ),
          React.createElement(Table, {
            rowKey: 'a',
            dataSource: [{ a: 1, b: 2 }],
            columns,
            size: 'middle',
            pagination: { pageSize: 20 },
            scroll: { x: 900 },
          }),
          React.createElement(Popconfirm, { title: 't', open: true }),
        ),
        React.createElement(
          Card,
          { title: 'Form' },
          React.createElement(
            Form,
            { layout: 'vertical', requiredMark: false, size: 'large' },
            React.createElement(
              Form.Item,
              { name: 'username', label: '用户名', rules: [{ required: true }] },
              React.createElement(Input, { prefix: React.createElement('span', null, 'u') }),
            ),
            React.createElement(
              Form.Item,
              { name: 'password', label: '密码', rules: [{ required: true }] },
              React.createElement(Input.Password, {
                prefix: React.createElement('span', null, 'p'),
              }),
            ),
            React.createElement(
              Form.Item,
              null,
              React.createElement(
                Button,
                { type: 'primary', htmlType: 'submit', size: 'large', block: true },
                '登录',
              ),
            ),
          ),
          React.createElement(Select, {
            value: 'x',
            style: { width: 160 },
            options: [{ value: 'x', label: 'X' }],
          }),
          React.createElement(Switch, { checked: true }),
        ),
        React.createElement(
          Card,
          { title: 'Descriptions' },
          React.createElement(
            Descriptions,
            { column: { xs: 1, sm: 2 }, size: 'small', bordered: true },
            React.createElement(Descriptions.Item, { label: 'L', children: 'V' }),
          ),
        ),
        React.createElement(Tag, { color: 'success' }, 'tag'),
        React.createElement(
          Tooltip,
          { title: 'tip', open: true },
          React.createElement('span', null, 'hover'),
        ),
        React.createElement(
          Typography,
          null,
          React.createElement(Typography.Title, { level: 2 }, 'Title'),
          React.createElement(Typography.Paragraph, null, 'Paragraph'),
          React.createElement(Typography.Text, { code: true }, 'code'),
        ),
      ),
    ),
  )
}

/** Render the showcase and return the serialised stylesheet. */
export function extractAntdCss() {
  const cache = createCache()
  renderToString(
    React.createElement(
      StyleProvider,
      { cache },
      React.createElement(
        ConfigProvider,
        { locale: zhCN, theme: themeConfig },
        React.createElement(App, null, React.createElement(Showcase)),
      ),
    ),
  )
  return extractStyle(cache, true)
}

export default function antdStaticStyles(outFile = 'src/styles/antd.css') {
  let root = process.cwd()
  return {
    name: 'antd-static-styles',
    configResolved(config: { root: string }) {
      // Vite runs with the `web/` directory as its root.
      root = config.root
    },
    buildStart(this: { info?: (message: string) => void }) {
      const css = extractAntdCss()
      const target = resolve(root, outFile)
      mkdirSync(dirname(target), { recursive: true })
      writeFileSync(target, css, 'utf8')
      this.info?.(`antd static styles -> ${outFile} (${css.length} bytes)`)
    },
  }
}
