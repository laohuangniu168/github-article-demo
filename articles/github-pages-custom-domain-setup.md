---
title: "GitHub Pages自定义域名设置完整教程"
description: "从 DNS 解析、GitHub 仓库配置到 HTTPS 启用，完整说明顶级域名与子域名绑定方法，并提供域名验证、故障排查和 SEO 迁移建议。"
---

# GitHub Pages自定义域名设置完整教程

## 配置前需要确认的事项

GitHub Pages 支持为用户站点、组织站点和项目站点绑定自定义域名。开始前应准备：

- 一个已经注册且可以管理 DNS 的域名；
- 一个已正常发布的 GitHub Pages 站点；
- 对目标仓库具有管理员权限；
- 明确要使用顶级域名还是子域名。

常见选择如下：

- 顶级域名：`example.com`
- `www` 子域名：`www.example.com`
- 其他子域名：`blog.example.com`

如果原站点地址是 `username.github.io/project/`，绑定后通常会变为 `example.com/project/` 或直接使用项目配置中生成的路径。需要特别检查静态网站中的资源链接，避免将 CSS、图片写死为 `/project/` 或旧域名地址。

建议先确定唯一的主域名，例如以 `example.com` 为主，`www.example.com` 作为跳转入口。GitHub Pages 一个站点只能设置一个 Custom domain，但可以通过同时配置顶级域名和 `www` 的 DNS 记录实现重定向。

## 在 GitHub Pages 中填写自定义域名

进入发布网站的仓库，依次打开：

1. **Settings**
2. 左侧菜单中的 **Pages**
3. 找到 **Custom domain**
4. 输入准备使用的域名，例如 `www.example.com`
5. 点击 **Save**

域名只填写主机名，不要添加协议和路径。正确示例：

```text
www.example.com
```

错误示例：

```text
https://www.example.com/
example.com/blog/
```

保存后，GitHub 通常会在 Pages 发布源中创建或更新一个名为 `CNAME` 的文件，内容只有自定义域名：

```text
www.example.com
```

如果网站通过 GitHub Actions 部署，应确认构建产物中保留了 `CNAME` 文件。某些静态网站生成器会清空输出目录，导致每次部署后自定义域名失效。可以把 `CNAME` 放入项目的静态资源目录，使其随构建结果一起发布。

Jekyll 项目常见位置是：

```text
CNAME
```

如果使用 VuePress、VitePress、Hugo 等工具，通常可将它放在会被原样复制到输出目录的静态文件目录中，具体位置以所用生成器的配置为准。

## 配置顶级域名的 DNS 解析

如果要绑定 `example.com`，需要在域名服务商的 DNS 控制台添加 A 记录，将顶级域名指向 GitHub Pages 官方 IP。

常用配置如下：

| 类型 | 主机记录 | 记录值 |
|---|---|---|
| A | `@` | `185.199.108.153` |
| A | `@` | `185.199.109.153` |
| A | `@` | `185.199.110.153` |
| A | `@` | `185.199.111.153` |

如果 DNS 服务商支持 IPv6，也可以添加 AAAA 记录：

```text
2606:50c0:8000::153
2606:50c0:8001::153
2606:50c0:8002::153
2606:50c0:8003::153
```

部分 DNS 平台支持 `ALIAS`、`ANAME` 或 CNAME Flattening，也可以用于顶级域名，但具体配置方式由服务商决定。普通 CNAME 通常不能直接用于根域名，因此最通用的方法仍是添加上述 A 记录。

应删除与这些记录冲突的旧 A、AAAA 或转发记录。TTL 可以暂时设置为 `600` 秒或使用默认值；域名稳定后再调整也可以。

GitHub 可能更新其 Pages IP 地址，长期使用时应以 GitHub 官方文档中公布的记录值为准，不要复制来源不明的 IP。

## 配置 www 或其他子域名

如果要使用 `www.example.com` 或 `blog.example.com`，应创建 CNAME 记录：

| 类型 | 主机记录 | 记录值 |
|---|---|---|
| CNAME | `www` | `username.github.io` |

其中 `username` 替换为 GitHub 用户名或组织名。即使项目站点原地址包含仓库路径，也不要把路径写入 CNAME。

正确写法：

```text
username.github.io
```

错误写法：

```text
username.github.io/project
https://username.github.io
```

建议同时配置顶级域名和 `www`：

- `example.com` 添加四条 A 记录；
- `www.example.com` 添加指向 `username.github.io` 的 CNAME；
- 在 GitHub Pages 中填写希望作为主站的那个域名。

GitHub Pages 在配置正确时可以处理顶级域名与对应 `www` 子域名之间的重定向。不要使用 `*.example.com` 之类的通配符 DNS 记录指向 GitHub Pages，因为未被仓库占用的子域名可能带来域名接管风险。

如果使用 Cloudflare 等提供代理功能的 DNS 服务，排查阶段可先将记录设为“仅 DNS”，避免代理缓存、SSL 模式或重定向规则干扰 GitHub 的域名校验。确认网站和 HTTPS 正常后，再根据实际需求测试代理功能。

## 验证域名并启用 HTTPS

DNS 记录保存后不会始终立即生效。通常几分钟内可以更新，但受 TTL 和递归 DNS 缓存影响，也可能需要更长时间。可以使用以下命令检查：

```bash
dig example.com A
dig www.example.com CNAME
```

Windows 用户可以使用：

```powershell
nslookup example.com
nslookup www.example.com
```

解析生效后，返回 GitHub 仓库的 **Settings → Pages**。当 GitHub 检测通过后，可以勾选 **Enforce HTTPS**，让 HTTP 请求跳转到 HTTPS。

如果该选项暂时不可用，通常是因为：

- DNS 尚未传播完成；
- 存在冲突的 A、AAAA 或 CNAME 记录；
- CNAME 指向了仓库路径而非 `username.github.io`；
- DNS 代理或 CAA 记录影响证书签发；
- 域名刚修改，GitHub 尚未完成证书配置。

不要频繁删除并重新添加域名，这可能让验证和证书签发重新开始。先确认 DNS 正确，再等待 GitHub 完成处理。

GitHub 还提供自定义域名验证功能。可在账户或组织的 Pages 设置中添加域名，并按提示创建类似下面的 TXT 记录：

```text
_github-pages-challenge-USERNAME.example.com
```

TXT 值由 GitHub 页面生成，不能照抄示例。验证完成后建议保留该记录，以降低其他 GitHub 用户使用该域名发布 Pages 站点的风险。域名验证和仓库中的 Custom domain 是两个不同步骤：前者证明域名归属，后者指定当前站点使用哪个域名。

## 常见故障与 SEO 迁移检查

出现 **Domain does not resolve to the GitHub Pages server** 时，优先检查 DNS 是否仍指向旧主机。出现 404 时，则应确认自定义域名填写在实际发布的仓库中，并检查 Pages 的发布分支、目录或 Actions 工作流是否成功。

如果首页正常但 CSS、图片或内部链接失效，通常是路径问题。例如：

```html
<link rel="stylesheet" href="/project/style.css">
```

绑定独立域名后，实际路径可能应改为：

```html
<link rel="stylesheet" href="/style.css">
```

也可以通过静态网站生成器的 `baseURL`、`base` 或站点 URL 配置统一处理，避免逐页修改。

从旧域名迁移时，还应完成这些检查：

- 将站点配置中的 URL 更新为新的 HTTPS 域名；
- 更新 canonical、Open Graph、站点地图和 RSS 中的绝对地址；
- 在 Google Search Console、Bing Webmaster Tools 等平台添加并验证新域名；
- 提交新站点地图，并持续观察抓取和索引状态；
- 检查旧的 `github.io` 地址是否正确跳转到自定义域名；
- 更新第三方统计、评论系统或 OAuth 服务中的允许域名。

这些操作有助于搜索引擎理解地址变化，但不能保证立即收录或提升排名。域名切换后出现一段时间的抓取波动是正常现象。

完成配置后，应分别访问 HTTP、HTTPS、顶级域名和 `www` 地址，确认它们最终进入同一个主域名，并检查证书、页面资源及内部链接。只要 GitHub Pages 设置、DNS 记录和构建产物中的 `CNAME` 保持一致，自定义域名通常就能稳定运行。
