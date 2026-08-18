---
title: "GitHub Pages robots.txt配置方法"
description: "介绍 GitHub Pages 中 robots.txt 的放置位置、规则写法、项目站点路径限制、部署验证方法，以及与 Sitemap 和 noindex 配合时的注意事项。"
---

# GitHub Pages robots.txt配置方法

## robots.txt 在 GitHub Pages 中如何生效

`robots.txt` 是放在网站域名根目录下的纯文本文件，用于向搜索引擎爬虫说明哪些路径可以抓取。爬虫通常只会查找以下地址：

```text
https://example.com/robots.txt
```

文件名必须使用小写，且应能通过根路径直接访问。放在 `/assets/robots.txt`、`/docs/robots.txt` 或其他子目录中，通常不会被当作该网站的标准 robots 文件。

需要注意，robots.txt 只是爬取规则，不是访问控制工具。遵守协议的搜索引擎会参考它，但它不能保护私密文件，也不能保证某个页面一定被收录或不被收录。

对于普通 GitHub Pages 网站，一个允许所有爬虫访问的基础配置如下：

```text
User-agent: *
Disallow:
```

如果网站有 Sitemap，可以同时声明：

```text
User-agent: *
Disallow:

Sitemap: https://example.com/sitemap.xml
```

`Sitemap` 建议填写完整的绝对地址，并与网站实际使用的 HTTPS 域名保持一致。

## 将文件放到正确的发布目录

GitHub Pages 支持从分支、`/docs` 目录或 GitHub Actions 构建结果进行发布。robots.txt 应放在“最终网站根目录”，而不一定是仓库根目录。

### 从分支根目录发布

如果 Pages 设置为从 `main` 分支的根目录发布，仓库结构可以是：

```text
repository/
├── index.html
├── robots.txt
├── sitemap.xml
└── assets/
```

提交并推送文件：

```bash
git add robots.txt
git commit -m "Add robots.txt"
git push
```

部署完成后访问：

```text
https://你的域名/robots.txt
```

### 从 `/docs` 目录发布

如果发布源设置为 `main` 分支下的 `/docs`，文件必须放入该目录：

```text
repository/
└── docs/
    ├── index.html
    ├── robots.txt
    └── sitemap.xml
```

放在仓库根目录的 robots.txt 不会自动出现在已发布网站中。

### 使用 GitHub Actions 发布

使用 Hugo、Vite、Astro 等工具构建网站时，应确保 robots.txt 被复制到最终构建目录的根部。常见做法是将它放在框架约定的静态资源目录中，例如 `public/robots.txt`，但具体目录取决于所用工具。

构建后应检查输出结果，例如：

```text
dist/
├── index.html
├── robots.txt
└── assets/
```

GitHub Pages 实际发布的是 Actions 上传的构建产物。仅在源码目录创建文件，但没有将其包含进构建产物，线上仍然会返回 404。

## 用户站点与项目站点的路径区别

GitHub Pages 有两种常见地址形式：

```text
用户或组织站点：
https://username.github.io/

项目站点：
https://username.github.io/project-name/
```

这一区别对 robots.txt 很重要。robots 协议要求文件位于域名根路径：

```text
https://username.github.io/robots.txt
```

对于项目站点，即使文件可以通过下面的地址访问：

```text
https://username.github.io/project-name/robots.txt
```

它也不是 `username.github.io` 这个主机的标准 robots.txt。搜索引擎通常不会把子目录中的文件作为该主机的 robots 规则。

如果需要管理 `username.github.io` 域名下项目站点的抓取规则，可以在名为 `username.github.io` 的用户站点仓库中发布根目录 robots.txt，并使用路径规则控制项目：

```text
User-agent: *
Disallow: /test-project/
Allow: /official-project/
```

这份文件作用于同一主机下的所有路径，因此修改前要检查是否会影响其他 GitHub Pages 项目。

更清晰的方案是为项目站点绑定独立自定义域名，例如：

```text
https://docs.example.com/
```

绑定后，该站点的标准 robots 地址就是：

```text
https://docs.example.com/robots.txt
```

此时项目发布结果根目录中的 robots.txt 可以直接生效。

## 常用规则及配置示例

如果只想禁止抓取测试目录和临时文件目录，可以写成：

```text
User-agent: *
Disallow: /drafts/
Disallow: /temp/

Sitemap: https://example.com/sitemap.xml
```

规则中的路径从域名根目录开始，并且区分具体路径。对于部署在自定义域名根部的网站，禁止某篇页面可以写成：

```text
User-agent: *
Disallow: /private-preview.html
```

如果网站实际运行在 GitHub Pages 项目路径下，则规则需要包含项目前缀：

```text
User-agent: *
Disallow: /project-name/drafts/
```

也可以为特定爬虫设置规则：

```text
User-agent: Googlebot
Disallow: /experimental/

User-agent: *
Disallow:
```

但不建议为了“优化抓取”编写大量复杂规则。静态站点通常规模较小，简单、明确的配置更容易维护。

以下写法表示禁止所有路径被抓取：

```text
User-agent: *
Disallow: /
```

它适合临时演示站点，但上线前必须谨慎检查。即使后来删除该规则，搜索引擎重新抓取和更新状态也可能需要时间。

## robots.txt 不能代替 noindex 或权限控制

`Disallow` 的含义是“不允许抓取”，不等同于“不允许出现在搜索结果中”。如果某个 URL 已被其他页面链接，搜索引擎仍可能仅根据链接信息展示该 URL，而无法抓取页面内容确认其状态。

如果希望公开页面不被索引，通常应在 HTML 的 `<head>` 中加入：

```html
<meta name="robots" content="noindex, follow">
```

此时不要同时通过 robots.txt 阻止该页面，否则爬虫可能无法读取页面内的 `noindex` 指令。

对于源代码、密钥、内部文档或个人数据，不能依赖 robots.txt。该文件本身是公开的，甚至会暴露被禁止目录的名称。敏感内容不应进入公开部署产物，并应通过真正的身份验证和访问权限进行保护。

## 部署后的检查方法

提交配置后，先在浏览器中直接访问 `/robots.txt`，确认返回的是文本内容而不是 GitHub 404 页面。也可以使用命令检查：

```bash
curl -I https://example.com/robots.txt
curl https://example.com/robots.txt
```

重点确认以下事项：

1. HTTP 状态码为 `200`。
2. 地址位于当前域名根路径。
3. 文件内容与仓库或构建产物一致。
4. `Sitemap` 地址可以正常访问。
5. 自定义域名、HTTPS 与 Sitemap 中的域名一致。
6. 项目站点规则包含正确的项目路径前缀。
7. 没有误写 `Disallow: /` 导致全站禁止抓取。

GitHub Pages 更新通常需要等待部署任务完成。可以在仓库的 **Actions** 或 **Settings → Pages** 中查看部署状态；若使用 CDN 或浏览器缓存，也可稍后重新请求并检查实际响应。

robots.txt 的核心是位置正确、规则简洁、与真实 URL 结构一致。用户站点可以直接控制域名根规则，而使用 `github.io/project-name/` 的项目站点需要特别注意根路径限制。配置完成后，以线上 `/robots.txt` 的实际响应为准，而不是只检查仓库中是否存在同名文件。
