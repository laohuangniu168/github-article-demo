---
title: "GitHub Pages Sitemap配置教程"
description: "介绍 GitHub Pages 站点生成、配置与提交 Sitemap 的完整流程，并涵盖 Jekyll、项目站点、自定义域名及常见错误排查。"
---

# GitHub Pages Sitemap配置教程

{% raw %}

## Sitemap 在 GitHub Pages 中的作用

Sitemap 是一个列出站点公开页面地址的 XML 文件，通常位于：

```text
https://example.com/sitemap.xml
```

它可以帮助搜索引擎发现页面、了解页面更新时间，但不代表其中的 URL 一定会被收录，也不能保证排名提升。对于导航层级较深、更新频繁或外部链接较少的 GitHub Pages 站点，提供 Sitemap 尤其有价值。

配置前应先确认站点属于哪种类型：

- 用户或组织站点：`https://username.github.io/`
- 项目站点：`https://username.github.io/repository/`
- 使用自定义域名的站点：如 `https://docs.example.com/`

站点类型会影响 Sitemap 中的 URL。如果项目站点漏掉仓库路径，生成的链接可能全部指向错误位置。

## 使用 jekyll-sitemap 自动生成

GitHub Pages 默认支持 Jekyll。对于使用 Jekyll 构建的站点，推荐通过 `jekyll-sitemap` 插件自动生成文件，它会根据页面和文章信息更新 URL，无需手工维护 XML。

在仓库根目录找到或创建 `_config.yml`，加入：

```yaml
url: "https://username.github.io"
baseurl: "/repository"

plugins:
  - jekyll-sitemap
```

如果是用户站点，通常不需要子路径：

```yaml
url: "https://username.github.io"
baseurl: ""

plugins:
  - jekyll-sitemap
```

使用自定义域名时，应改为实际访问域名：

```yaml
url: "https://docs.example.com"
baseurl: ""

plugins:
  - jekyll-sitemap
```

其中：

- `url` 填写协议和域名，不要在末尾添加斜杠。
- `baseurl` 填写站点部署子路径。
- 项目站点的 `baseurl` 通常是仓库名，例如 `/blog`。
- 自定义域名直接指向站点时，`baseurl` 一般为空。

提交并等待 GitHub Pages 构建完成后，访问对应地址：

```text
https://username.github.io/repository/sitemap.xml
```

或：

```text
https://docs.example.com/sitemap.xml
```

如果本地使用 Bundler 构建，还可在 `Gemfile` 中使用 GitHub Pages 依赖：

```ruby
gem "github-pages", group: :jekyll_plugins
```

然后执行：

```bash
bundle install
bundle exec jekyll serve
```

本地生成的 `_site/sitemap.xml` 可用于检查结果。不要将 `_site` 当作源文件提交，除非你的部署流程明确要求发布该目录。

## 非 Jekyll 站点手动创建 Sitemap

React、Vue、Hugo 或纯 HTML 项目如果通过 GitHub Actions 自行构建，`jekyll-sitemap` 不会自动参与构建。此时可以让所用框架生成 Sitemap，也可以直接创建 `sitemap.xml`。

最小示例如下：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/</loc>
  </url>
  <url>
    <loc>https://example.com/about/</loc>
    <lastmod>2025-03-01</lastmod>
  </url>
</urlset>
```

保存时应确保该文件最终进入网站发布目录。例如构建结果发布自 `dist`，那么 Sitemap 也必须出现在 `dist/sitemap.xml`，而不是只存在于源代码根目录。

编写时注意以下规则：

1. `<loc>` 必须使用完整的绝对 URL。
2. URL 应与站点实际使用的 HTTPS 地址一致。
3. 只列出希望公开且能够正常访问的规范页面。
4. 不要加入 404 页面、登录页、重定向地址或被禁止抓取的 URL。
5. `<lastmod>` 应反映真实更新时间，不宜每次构建都无条件改成当前日期。
6. XML 中的特殊字符需要转义，例如参数中的 `&` 应写成 `&amp;`。

单个 Sitemap 最多可包含 50,000 个 URL，未压缩文件大小上限为 50MB。普通 GitHub Pages 站点通常远达不到这一限制。

## 配置 robots.txt 提示搜索引擎

可以在站点发布根目录创建 `robots.txt`，并写入 Sitemap 的完整地址：

```text
User-agent: *
Allow: /

Sitemap: https://example.com/sitemap.xml
```

对于项目站点，Sitemap 地址应包含仓库路径：

```text
Sitemap: https://username.github.io/repository/sitemap.xml
```

需要注意，`robots.txt` 按规范应位于域名根目录。例如搜索引擎会查找 `https://username.github.io/robots.txt`，而不是把项目子目录中的文件视为该主机的标准 robots 文件。因此，多个项目共用 `username.github.io` 域名时，不能只依赖项目目录内的 `robots.txt`。

项目站点仍可通过站内链接、搜索引擎管理平台或其他可抓取页面直接提供 Sitemap 地址。使用独立自定义域名则更方便管理根目录下的 `robots.txt`。

不要为了“节省抓取”而随意添加：

```text
Disallow: /
```

这会阻止允许遵守 robots 协议的爬虫抓取整个站点。robots 规则也不是隐藏敏感内容的安全措施，私密文件不应发布到公开仓库或公开 Pages 站点。

## 验证并提交 Sitemap

部署完成后，先在浏览器中打开 `sitemap.xml`。浏览器显示“此 XML 文件没有关联样式”通常不是错误，只要 XML 内容可以正常读取即可。

建议依次检查：

- 请求返回 HTTP 200，而不是 404 或重定向循环。
- `<loc>` 中没有 `localhost`、测试域名或错误仓库路径。
- 页面 URL 可以公开访问。
- HTTP 与 HTTPS、带 `www` 与不带 `www` 的版本保持一致。
- Sitemap 地址与页面中的规范 URL 方向一致。
- XML 标签闭合正确，文件编码为 UTF-8。

随后可在 Google Search Console 中验证站点资源，并在“Sitemap”功能中提交文件地址。Bing Webmaster Tools 也支持提交 Sitemap。提交后显示“成功”只说明文件能够读取，并不等于其中所有页面都会被索引。

如果使用自定义域名，建议验证该域名对应的资源，而不是只验证 `username.github.io`。更换域名后，也应更新 `_config.yml`、Sitemap、站内链接和搜索引擎平台中的提交记录。

## 常见问题与排查方法

### 访问 sitemap.xml 返回 404

先确认 GitHub Pages 最近一次部署是否成功。在仓库的 **Actions** 或 **Settings → Pages** 中查看构建状态，并检查插件名称是否写在 `plugins` 下。

如果使用自定义构建流程，还要确认生成文件已被复制到最终发布目录。源目录存在文件，不代表部署产物中一定存在。

### Sitemap 中缺少仓库路径

例如实际站点为：

```text
https://username.github.io/docs/
```

但文件中生成的是：

```text
https://username.github.io/page/
```

通常是 `_config.yml` 中的 `baseurl` 未设置。应配置为：

```yaml
baseurl: "/docs"
```

修改后重新构建，并检查模板中的内部链接是否也正确使用了站点基础路径。

### Sitemap 中仍是旧域名

检查 `_config.yml` 的 `url`、自定义域名设置以及仓库中的 `CNAME` 文件。GitHub Pages 启用自定义域名并不会自动修正所有手写 XML 或模板变量，旧地址需要在源文件或构建配置中更新。

### 页面不想出现在 Sitemap 中

不应公开或不适合作为搜索结果入口的页面，可以从手工 XML 中删除；使用 Jekyll 插件时，则应在对应内容的页面级配置中将 `sitemap` 设为 `false`。同时检查该页面是否仍被站内导航大量链接，以及是否需要设置合适的 `noindex`。从 Sitemap 删除 URL 本身并不能阻止搜索引擎通过其他链接发现它。

完成配置后，重点不是频繁重复提交，而是保证 Sitemap 地址长期稳定、URL 可访问、域名和路径正确，并在新增或删除页面时同步更新。对于 Jekyll 站点，自动生成通常最省维护成本；对于自定义构建项目，则应把 Sitemap 生成纳入部署流程，避免线上文件与实际内容脱节。

{% endraw %}
