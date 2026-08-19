---
title: "GitHub Pages网站部署完整教程"
description: "从仓库创建、分支发布到 GitHub Actions、独立域名和 HTTPS 配置，完整讲解 GitHub Pages 部署流程及常见故障处理。"
---

# GitHub Pages网站部署完整教程

{% raw %}

## 部署前需要了解的限制与站点类型

GitHub Pages 是 GitHub 提供的静态网站托管服务，适合部署个人主页、项目文档、博客以及前端构建产物。它可以直接发布 HTML、CSS、JavaScript 和图片，但不能运行 PHP、Java、Node.js 服务端程序，也不提供传统数据库。

GitHub Pages 主要有两种站点形式：

- **用户或组织站点**：仓库名必须是 `用户名.github.io`，默认地址为 `https://用户名.github.io/`。
- **项目站点**：仓库名称可以自定义，默认地址为 `https://用户名.github.io/仓库名/`。

项目站点多了一层仓库路径。使用 Vite、Vue、React 等工具构建时，需要特别处理资源基础路径，否则部署后可能出现脚本和样式 404。

开始前请准备：

1. 一个 GitHub 账号；
2. 已安装 Git，可通过 `git --version` 检查；
3. 至少包含 `index.html` 的静态网站；
4. 如果使用前端框架，确保本地执行构建命令后能生成 `dist`、`build` 或其他静态输出目录。

## 使用分支快速部署静态网站

对于纯 HTML 网站，最简单的方法是直接从仓库分支发布。

新建仓库后，在本地网站目录执行：

```bash
git init
git add .
git commit -m "Initial website"
git branch -M main
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main
```

确保仓库根目录存在入口文件：

```text
index.html
style.css
assets/
```

然后进入 GitHub 仓库，依次打开：

1. **Settings**
2. 左侧菜单中的 **Pages**
3. 在 **Build and deployment** 下，将 Source 选择为 **Deploy from a branch**
4. 分支选择 `main`
5. 目录选择 `/ (root)`
6. 点击 **Save**

如果网站文件放在 `docs` 目录，也可以选择 `/docs`。保存后 GitHub 会启动部署，通常需要等待几分钟。部署状态可在仓库的 **Actions** 页面查看。

部署完成后，项目站点地址通常是：

```text
https://你的用户名.github.io/仓库名/
```

若使用仓库名为 `你的用户名.github.io` 的用户站点，则访问地址不包含仓库路径。

GitHub Pages 从分支发布时可能使用 Jekyll 处理文件。如果项目不需要 Jekyll，或者包含以下划线开头的目录，可以在发布目录创建空文件：

```text
.nojekyll
```

这样可避免部分静态资源被 Jekyll 规则忽略。

## 使用 GitHub Actions 自动构建和发布

Vue、React、Vite 等项目不能直接发布源代码，通常要先安装依赖并执行构建。此时可使用 GitHub Actions，在每次推送代码后自动生成并部署静态文件。

在仓库中创建：

```text
.github/workflows/deploy.yml
```

以输出目录为 `dist` 的 npm 项目为例：

```yaml
name: Deploy GitHub Pages

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm

      - name: Install dependencies
        run: npm ci

      - name: Build
        run: npm run build

      - name: Setup Pages
        uses: actions/configure-pages@v5

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./dist

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    needs: build
    steps:
      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@v4
```

提交工作流文件后，还要进入 **Settings → Pages**，将 Source 设置为 **GitHub Actions**。之后每次向 `main` 分支推送代码，工作流都会重新构建并部署。

如果实际输出目录是 `build`，应把 `path: ./dist` 改为 `path: ./build`。构建失败时，应先查看 Actions 日志，而不是反复修改 Pages 地址。

## 处理项目路径和前端路由

项目站点位于 `/仓库名/` 下，资源路径不能始终假设网站部署在域名根目录。

例如 Vite 项目可在 `vite.config.js` 中配置：

```javascript
import { defineConfig } from 'vite'

export default defineConfig({
  base: '/仓库名/'
})
```

如果使用自定义域名并直接部署在域名根路径，通常应改为：

```javascript
export default defineConfig({
  base: '/'
})
```

HTML 中也应避免错误的绝对路径。例如项目站点中的：

```html
<script src="/assets/app.js"></script>
```

会请求 `https://用户名.github.io/assets/app.js`，忽略仓库路径。应通过构建工具生成正确地址，或使用适合当前目录结构的相对路径。

GitHub Pages 没有可配置的服务器重写规则。使用 History 模式的单页应用时，直接访问 `/about` 可能返回 404。可考虑使用 Hash 路由，例如 `/#/about`；也可以设计自定义 `404.html`，但它并不等同于服务器端的完整路由回退。

## 配置自定义域名与 HTTPS

在 **Settings → Pages → Custom domain** 中填写域名，例如：

```text
www.example.com
```

对于 `www` 等子域名，在 DNS 服务商处添加 CNAME 记录：

```text
类型：CNAME
主机记录：www
目标：你的用户名.github.io
```

目标中不要加入 `https://`、仓库名或路径。

如果使用根域名 `example.com`，可添加 GitHub Pages 官方提供的 A 记录：

```text
185.199.108.153
185.199.109.153
185.199.110.153
185.199.111.153
```

DNS 修改可能需要一段时间传播。GitHub 检测到域名解析正确后，可以启用 **Enforce HTTPS**。若选项暂时不可用，应先确认 DNS 记录没有冲突，并等待证书签发完成。

建议同时使用 GitHub 提供的域名验证功能，通过 DNS TXT 记录验证域名所有权，以降低域名被其他仓库错误占用的风险。不要随意设置指向 GitHub Pages 的通配符 DNS 记录。

## 基础 SEO 配置与常见问题

每个页面至少应提供独立、准确的标题和描述：

```html
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>页面主题 - 网站名称</title>
  <meta name="description" content="概括当前页面内容的自然描述">
  <link rel="canonical" href="https://www.example.com/current-page/">
</head>
```

还可以根据网站规模配置：

- `robots.txt`，说明允许抓取的范围并提供站点地图地址；
- `sitemap.xml`，列出希望搜索引擎发现的规范页面；
- 自定义 `404.html`，帮助用户返回有效页面；
- 清晰的内部链接和语义化标题结构；
- 图片 `alt` 文本、合理的文件体积和移动端布局。

GitHub Pages 能提供公开访问和 HTTPS，但不代表页面一定会被搜索引擎收录或获得更高排名。内容质量、可抓取性、外部信号和搜索引擎判断都会影响结果。

如果部署后出现异常，可按以下顺序检查：

1. **访问 404**：确认 Pages 已启用，地址是否包含仓库名。
2. **样式或脚本丢失**：检查浏览器开发者工具中的请求路径及构建 `base` 配置。
3. **Actions 部署失败**：查看安装、构建和上传步骤的错误日志。
4. **更新未生效**：确认代码已推送到正确分支，并检查最新工作流是否成功。
5. **自定义域名报错**：核对 CNAME、A 记录及仓库中的域名设置，避免重复或冲突记录。

对于简单静态页面，分支发布足够直接；需要编译的前端项目更适合使用 GitHub Actions。把发布目录、基础路径、域名解析和 HTTPS 配置逐项确认后，就能建立一套可重复、易维护的部署流程。

{% endraw %}
