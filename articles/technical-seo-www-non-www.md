---
title: "WWW与非WWW域名SEO规范化方法"
description: "系统讲解如何统一 WWW 与非 WWW 域名，包括 DNS、301 重定向、Canonical、站内链接及 GitHub Pages 配置与验证方法。"
---

# WWW与非WWW域名SEO规范化方法

{% raw %}

## 为什么需要统一域名版本

从技术上看，`https://www.example.com/page` 与 `https://example.com/page` 是两个不同的 URL。若两者都能返回相同内容且没有明确规范化，可能产生以下问题：

- 搜索引擎需要自行判断哪个版本是主版本；
- 外部链接权重、抓取信号可能分散在不同 URL；
- 数据分析中出现重复页面；
- Sitemap、内部链接与搜索结果展示的域名不一致；
- 相同页面可能以 HTTP、HTTPS、WWW、非 WWW 等多个版本存在。

规范化的目标不是让两套地址并存，而是选定一个首选版本，并将其他版本永久重定向到它。例如决定使用：

```text
https://example.com/
```

那么下面这些地址都应跳转到该版本：

```text
http://example.com/
http://www.example.com/
https://www.example.com/
```

选择 WWW 还是非 WWW 通常不会直接决定排名。更重要的是全站一致、重定向正确，并且长期保持稳定。

## 先确定首选域名

两种形式都可以正常用于 SEO：

- 非 WWW：`https://example.com`
- WWW：`https://www.example.com`

非 WWW 更简洁，适合品牌站、博客和小型网站。WWW 本质上是子域名，在大型架构中更容易进行独立 DNS、CDN 或 Cookie 管理，但这并不意味着普通网站必须使用 WWW。

选择时可参考以下因素：

1. **现有收录情况**：优先保留已被大量收录和引用的版本。
2. **外部链接数量**：如果主要外链集中在某个版本，轻易切换会增加迁移成本。
3. **历史重定向**：避免在两个版本之间反复更改。
4. **平台限制**：确认托管平台、CDN 和证书能够覆盖两个主机名。
5. **品牌展示习惯**：营销材料和线下宣传最好保持一致。

如果网站已经运营，不建议仅因为“更美观”而随意切换。切换本身属于 URL 迁移，需要重新抓取和处理信号，短期内可能出现波动。

## DNS 与 HTTPS 的基础配置

DNS 负责把域名解析到服务器，不负责网页重定向。仅仅删除非首选域名的 DNS 记录，会导致用户无法访问，而不是自动跳转。

假设首选版本为非 WWW，通常需要：

- 为根域名 `example.com` 配置 A、AAAA 或托管商支持的 ALIAS/ANAME 记录；
- 为 `www.example.com` 配置 CNAME，指向托管平台要求的目标，或解析到能够执行跳转的服务器；
- 确保两个主机名都能到达 Web 服务或重定向服务。

如果首选版本是 WWW，则 `www.example.com` 通常使用 CNAME；根域名仍要配置可用的解析，以便接收请求并跳转到 WWW。

HTTPS 证书也必须覆盖两个域名：

```text
example.com
www.example.com
```

否则用户访问非首选版本时，浏览器会在重定向发生前先建立 TLS 连接。如果证书不包含该域名，用户看到的将是安全警告，而不是正常的 301 跳转。

配置 HSTS 前应先确认 HTTPS、证书续期和所有子域名都运行稳定。尤其不要在未核查子域名的情况下贸然启用 `includeSubDomains`。

## 使用 301 重定向统一所有 URL

服务器端永久重定向是规范化的核心。重定向应满足三个条件：

- 使用 `301` 或 `308` 永久重定向；
- 保留原路径和查询参数；
- 尽量一步到达最终 HTTPS 首选域名。

例如：

```text
http://www.example.com/products?id=8
```

应直接跳转到：

```text
https://example.com/products?id=8
```

避免先跳 HTTPS，再去掉 WWW，形成多次跳转。

### Nginx 示例

首选域名为非 WWW 时，可以为其他版本建立跳转服务器块：

```nginx
server {
    listen 80;
    server_name example.com www.example.com;
    return 301 https://example.com$request_uri;
}

server {
    listen 443 ssl;
    server_name www.example.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    return 301 https://example.com$request_uri;
}
```

正式内容由 `https://example.com` 对应的 HTTPS `server` 块提供。`$request_uri` 会保留路径与查询字符串。

若首选版本为 WWW，只需把目标改为：

```nginx
return 301 https://www.example.com$request_uri;
```

### Apache 示例

在可使用 `mod_rewrite` 的环境中，首选非 WWW 可配置：

```apache
RewriteEngine On

RewriteCond %{HTTPS} !=on [OR]
RewriteCond %{HTTP_HOST} ^www\.example\.com$ [NC]
RewriteRule ^ https://example.com%{REQUEST_URI} [R=301,L]
```

具体写入虚拟主机配置还是 `.htaccess`，取决于服务器权限。上线前应确认规则不会与 CMS、缓存插件或 HTTPS 跳转规则冲突。

使用 Cloudflare、负载均衡器或托管平台时，也可以在边缘层创建永久重定向规则。关键不是工具名称，而是确认状态码、目标地址、路径和参数都正确。不要同时在 CDN、源站和插件中配置互相矛盾的跳转，否则容易形成循环。

## 同步 Canonical、内部链接与 Sitemap

301 重定向之后，还应统一页面中的其他信号。每个可索引页面可以输出指向首选 URL 的 Canonical：

```html
<link rel="canonical" href="https://example.com/products/">
```

Canonical 应使用完整绝对地址，并与最终可访问 URL 一致。不要出现以下矛盾：

- 页面跳转到非 WWW，Canonical 却指向 WWW；
- Canonical 指向返回 404 或被 `noindex` 的页面；
- 多个重复页面互相指定为规范版本；
- 所有页面都错误地指向首页。

同时检查：

- 导航、面包屑、正文链接和图片链接；
- XML Sitemap 中的页面地址；
- Open Graph、结构化数据中的 URL；
- RSS、邮件模板及分享按钮；
- 多语言页面的 `hreflang`；
- 广告落地页和第三方平台中的链接。

Sitemap 只应提交首选版本中返回 `200` 的规范 URL，不应包含会被 301 重定向的旧地址。站内链接也应直接指向最终 URL，减少不必要的跳转和抓取消耗。

## GitHub Pages 的处理方式

GitHub Pages 支持为站点设置自定义域名。域名应在仓库 Pages 设置中配置，系统通常会生成或更新 `CNAME` 文件；不要仅手动添加文件而忽略仓库设置和 DNS 验证。

使用根域名时，应按照 GitHub Pages 当前文档配置根域名的 DNS 记录，并为 `www` 子域名设置对应的 CNAME。使用 WWW 作为主域名时，同样要让根域名具备有效解析。GitHub Pages 在两个域名均正确配置的情况下，可以处理根域名与 WWW 之间的跳转。

需要注意：

- 根域名通常不能直接使用普通 CNAME，应使用 GitHub 提供的 A/AAAA 记录，或 DNS 服务商支持的 ALIAS/ANAME；
- 不要照搬过期 IP，应以 GitHub 官方文档公布的记录为准；
- 在 Pages 设置中启用 HTTPS，并等待证书签发完成；
- 一个仓库的自定义域名设置应明确指向实际首选版本；
- 若前面还使用 Cloudflare，应避免额外规则与 GitHub Pages 跳转冲突。

配置完成后，分别访问 HTTP、HTTPS、WWW 和非 WWW 四种组合，确认最终只保留一个版本。

## 如何检查规范化是否生效

可以使用 `curl` 查看响应头：

```bash
curl -I http://www.example.com/test?x=1
curl -I https://www.example.com/test?x=1
curl -I http://example.com/test?x=1
curl -I https://example.com/test?x=1
```

非首选版本应返回类似：

```text
HTTP/2 301
location: https://example.com/test?x=1
```

首选版本则应正常返回 `200`。此外还要检查：

1. 是否存在重定向循环；
2. 路径、参数和大小写是否被意外改变；
3. HTTPS 证书是否覆盖两个域名；
4. Canonical 是否指向最终地址；
5. Sitemap 是否只包含规范 URL；
6. Google Search Console 的网址检查结果是否识别到正确规范页。

Search Console 可添加域名资源，以汇总不同协议和子域名的数据；如需分别排查，也可建立 URL 前缀资源。完成切换后，应继续保留旧版本的 301，而不是在搜索结果更新后立即删除。

WWW 与非 WWW 的规范化本质上是一套一致性工程：DNS 保证两种地址可达，证书保证跳转前连接安全，301 指向唯一版本，Canonical、Sitemap 和内部链接再共同强化这一选择。配置是否可靠，应以实际响应状态和抓取结果为准，而不是仅看浏览器地址栏是否最终跳转。

{% endraw %}
