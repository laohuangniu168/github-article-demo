---
title: "SEO 301重定向配置与优化方法"
description: "本文讲解 301 重定向的适用场景、Nginx、Apache 与 IIS 配置方法，以及迁移检查、链路优化和常见错误排查。"
---

# SEO 301重定向配置与优化方法

{% raw %}

301 重定向表示资源已永久迁移到新地址。服务器返回 `301 Moved Permanently` 后，浏览器和搜索引擎会访问响应头 `Location` 指向的 URL。它适合域名更换、HTTPS 迁移、URL 结构调整及重复页面合并，但配置不当也可能造成循环跳转、权重信号分散或页面无法访问。

## 哪些情况应该使用 301 重定向

常见使用场景包括：

- 旧域名永久迁移到新域名；
- HTTP 统一跳转到 HTTPS；
- `www` 与非 `www` 版本统一；
- 页面路径永久变化，例如 `/product/123` 改为 `/products/123`；
- 删除重复页面，并将其合并到内容最相关的页面；
- URL 大小写、尾斜杠或参数规则需要统一。

如果页面只是暂时不可用，之后还会恢复原地址，应考虑 `302` 或 `307`。对于必须保留请求方法和请求体的接口，`308` 通常比 `301` 更合适，因为部分客户端处理 301 时可能把 POST 改成 GET。

301 也不应该成为所有失效页面的统一处理方式。某个页面没有可替代内容时，可以正常返回 `404`；已明确永久删除且无需保留时，也可以返回 `410`。将大量无关旧页面全部跳转到首页，不仅影响用户体验，也可能被搜索引擎视为软 404。

## Nginx 配置方法

修改 Nginx 配置前应先备份文件，并使用 `nginx -t` 检查语法。

### 整站更换域名

```nginx
server {
    listen 80;
    server_name old.example.com www.old.example.com;

    return 301 https://www.new.example.com$request_uri;
}
```

`$request_uri` 会保留原始路径和查询字符串。例如：

```text
http://old.example.com/news/1?id=8
```

将跳转到：

```text
https://www.new.example.com/news/1?id=8
```

如果新站路径结构与旧站不同，不应直接整站映射，而应针对重要页面建立旧 URL 与新 URL 的对应关系。

### HTTP 跳转到 HTTPS

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    return 301 https://example.com$request_uri;
}
```

HTTPS 站点还需要在监听 `443` 的 `server` 块中正确配置证书。不要让 HTTPS 配置再次跳回 HTTP，否则会产生重定向循环。

### 单个页面跳转

```nginx
location = /old-page {
    return 301 /new-page;
}
```

精确匹配使用 `location =`，可以避免 `/old-page-2` 等无关地址被误匹配。配置完成后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## Apache 与 IIS 配置方法

### Apache `.htaccess`

Apache 需要启用 `mod_rewrite`。整站域名迁移可写为：

```apache
RewriteEngine On

RewriteCond %{HTTP_HOST} ^(www\.)?old\.example\.com$ [NC]
RewriteRule ^ https://www.new.example.com%{REQUEST_URI} [R=301,L,NE]
```

单个页面跳转：

```apache
RewriteEngine On
RewriteRule ^old-page/?$ /new-page [R=301,L]
```

规则通常应放在 WordPress 等 CMS 自动生成的重写规则之前，否则请求可能先被应用程序接管。修改后还应确认虚拟主机允许 `.htaccess` 覆盖规则，例如相关目录配置中包含适当的 `AllowOverride` 设置。

如果可以编辑 Apache 虚拟主机配置，简单路径跳转也可以使用：

```apache
Redirect 301 /old-page https://example.com/new-page
```

### IIS `web.config`

IIS 可通过 URL Rewrite 模块配置永久跳转：

```xml
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="Old page redirect" stopProcessing="true">
          <match url="^old-page/?$" />
          <action
            type="Redirect"
            url="/new-page"
            redirectType="Permanent"
            appendQueryString="true" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

部署前应确认服务器已安装 URL Rewrite 模块，并在测试环境验证规则，避免影响现有路由。

## GitHub Pages 等静态托管的限制

GitHub Pages 不提供 Nginx、Apache 或 `.htaccess` 级别的服务器配置，因此不能直接为任意路径设置真正的服务端 301。使用 HTML 的 `meta refresh` 或 JavaScript 跳转，只是客户端跳转，不能等同于 HTTP 301 响应。

如果静态站点需要可靠的永久重定向，可以采用以下方案：

- 在支持重定向规则的 CDN 或边缘平台处理；
- 将旧域名接入可配置 301 的反向代理；
- 保留一台轻量服务器专门返回跳转响应；
- 使用托管平台明确提供的重定向配置功能，并检查实际状态码。

GitHub Pages 支持绑定自定义域名，但这不代表它支持任意旧路径到新路径的 301 映射。迁移前应根据实际托管架构验证响应头，而不是只观察浏览器是否跳到了新页面。

## SEO 迁移与重定向优化

301 能传递页面迁移信号，但不意味着排名或收录一定保持不变。为了减少迁移过程中的信号损耗，应重点处理以下事项。

### 建立一对一映射

优先将旧页面跳转到主题、内容和搜索意图最接近的新页面。不要为了省事，把所有旧 URL 都重定向到首页。

可先整理映射表：

| 旧 URL | 新 URL | 处理方式 |
|---|---|---|
| `/blog/seo-301` | `/seo/301-guide` | 301 |
| `/old-product-a` | `/products/a` | 301 |
| `/expired-event` | 无替代内容 | 404 或 410 |

### 避免重定向链

以下链路会增加请求次数：

```text
旧地址 → 中间地址 → HTTPS 地址 → 最终地址
```

应尽量改为：

```text
旧地址 → 最终地址
```

同时更新站内链接、导航、面包屑、结构化数据、XML Sitemap 和 canonical，使其直接指向最终 URL。canonical 只能表达规范页面偏好，不能代替必要的 301。

### 保持规则稳定

域名迁移后，不要过早关闭旧域名或删除跳转。搜索引擎和外部链接可能在较长时间内继续访问旧地址。通常至少应稳定保留一年，条件允许时可长期保留，并持续续费旧域名及维护 HTTPS 证书。

整站迁移还应在 Google Search Console、Bing Webmaster Tools 等平台验证新旧站点，根据平台功能提交地址变更或新 Sitemap，并监控抓取错误、索引变化和服务器日志。

## 检查状态码与常见错误

可以使用 `curl` 检查单个 URL：

```bash
curl -I http://old.example.com/old-page
```

正确响应应包含：

```text
HTTP/1.1 301 Moved Permanently
Location: https://new.example.com/new-page
```

查看完整跳转链：

```bash
curl -IL http://old.example.com/old-page
```

上线后重点排查：

1. **循环跳转**：HTTP 与 HTTPS、`www` 与非 `www` 规则互相冲突。
2. **多次跳转**：旧域名先切协议，再切主机名，最后才调整路径。
3. **错误匹配**：正则范围过大，导致正常页面也被重定向。
4. **目标页面异常**：301 最终落到 404、500 或另一个跳转地址。
5. **参数丢失或误保留**：广告参数通常可保留，但旧系统的功能参数可能需要重新映射。
6. **缓存干扰**：浏览器和 CDN 可能长期缓存 301，测试阶段可先使用临时重定向，确认无误后再改为永久状态码。
7. **只做跳转不改站内链接**：用户仍需经过重定向，搜索引擎也会重复抓取旧地址。

301 配置的核心不是“让地址能够跳转”，而是让每个旧 URL 以最短路径到达正确的新页面，并确保最终页面可访问、可索引且站内信号一致。上线前小范围测试，上线后结合响应头、日志与搜索平台数据持续检查，通常比一次性批量添加规则更稳妥。

{% endraw %}
