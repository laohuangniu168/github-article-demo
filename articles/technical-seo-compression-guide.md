---
title: "Gzip与Brotli压缩对SEO性能的影响"
description: "解析 Gzip 与 Brot利的压缩效率、SEO 间接影响、服务器配置方法及检测步骤，并说明如何避免高压缩级别、缓存错误和重复压缩带来的性能问题。"
---

# Gzip与Brotli压缩对SEO性能的影响

{% raw %}

## 压缩为什么会影响 SEO 性能

Gzip 和 Brotli 都属于 HTTP 内容编码。浏览器请求页面时，会通过 `Accept-Encoding` 告诉服务器自己支持哪些压缩格式；服务器压缩响应后，通过 `Content-Encoding: gzip` 或 `Content-Encoding: br` 返回。

压缩不会改变 HTML、CSS 和 JavaScript 的功能，主要作用是减少网络传输字节。例如，一个未经压缩的 300 KB JavaScript 文件，经过文本压缩后可能只需传输几十 KB。具体比例取决于文件内容，不能用固定百分比衡量。

它们并不是“直接排名因素”，但可能通过以下环节间接影响搜索表现：

- 缩短 HTML、CSS、JavaScript 等资源的下载时间；
- 改善移动网络或高延迟环境下的加载体验；
- 降低部分页面出现渲染阻塞的概率；
- 为 LCP、INP 等核心网页指标的优化创造条件；
- 减少服务器出口流量，并可能提升高并发下的响应能力。

需要注意的是，压缩无法解决慢查询、第三方脚本过多、图片尺寸不合理或主线程阻塞等问题。如果页面瓶颈在后端 TTFB 或 JavaScript 执行时间，单独开启压缩不会带来根本改善。

## Gzip 与 Brotli 应该如何选择

Gzip 历史较长，服务器、CDN、浏览器和各种代理环境对它的支持都很成熟。Brotli 使用 `br` 作为内容编码，通常能对 HTML、CSS、JavaScript、SVG、JSON 等文本资源取得比 Gzip 更小的体积。

| 对比项 | Gzip | Brotli |
|---|---|---|
| 浏览器兼容性 | 非常广泛 | 现代浏览器普遍支持 |
| 文本压缩率 | 良好 | 通常更优 |
| 实时压缩成本 | 相对较低 | 高级别时可能较高 |
| 常见使用方式 | 动态压缩、CDN 压缩 | CDN、静态预压缩或中等级别动态压缩 |
| 推荐定位 | 兼容性回退 | 支持时优先返回 |

实际部署不必二选一。更合理的方案是同时支持两者：

1. 客户端支持 Brotli 时返回 `Content-Encoding: br`；
2. 不支持 Brotli但支持 Gzip 时返回 `Content-Encoding: gzip`；
3. 两者都不支持时返回未压缩内容。

对于动态请求，不建议盲目使用 Brotli 最高压缩级别。压缩级别越高，通常越消耗 CPU，节省的少量字节未必能抵消服务器实时计算造成的延迟。静态资源可以在构建阶段生成 `.br` 和 `.gz` 文件，从而避免每次请求重复压缩。

## 哪些资源值得压缩

优先压缩具有较高重复度的文本内容：

- HTML；
- CSS；
- JavaScript；
- JSON、XML；
- SVG；
- Web App Manifest；
-纯文本和字体文件，但应根据服务器与 CDN 的实际支持测试。

JPEG、PNG、WebP、AVIF、MP4、ZIP、PDF 等格式通常已经使用自身的压缩方式，再进行 Gzip 或 Brotli 压缩往往收益很小，还会浪费 CPU。是否压缩 PDF、字体等文件也不宜只看扩展名，应比较压缩前后的体积和响应耗时。

还可以设置最小压缩尺寸。例如，小于 1 KB 的响应即使压缩，节省的字节也可能不足以覆盖额外处理和响应头成本。

服务器应正确返回：

```http
Content-Encoding: br
Vary: Accept-Encoding
```

`Vary: Accept-Encoding` 用于提醒缓存系统：不同压缩能力的客户端可能对应不同响应版本。如果 CDN 缓存键或代理配置忽略该差异，可能把 Brotli 内容错误地发给不支持它的客户端。

## Nginx 与 Apache 配置示例

Nginx 通常自带 Gzip 支持，可在 `http` 或合适的服务器配置块中设置：

```nginx
gzip on;
gzip_comp_level 5;
gzip_min_length 1024;
gzip_vary on;

gzip_types
    text/plain
    text/css
    text/javascript
    application/javascript
    application/json
    application/xml
    image/svg+xml;
```

Nginx 官方基础安装不一定包含 Brotli 模块。只有确认当前发行版、托管平台或自编译版本已经安装对应模块后，才能使用类似配置：

```nginx
brotli on;
brotli_comp_level 5;
brotli_static on;

brotli_types
    text/plain
    text/css
    text/javascript
    application/javascript
    application/json
    application/xml
    image/svg+xml;
```

不要直接复制 Brotli 指令后重启生产服务器，应先执行：

```bash
nginx -t
```

Apache 可分别通过 `mod_deflate` 和 `mod_brotli` 实现压缩。确认模块已启用后，可按 MIME 类型配置：

```apache
<IfModule mod_deflate.c>
  AddOutputFilterByType DEFLATE text/html text/plain text/css
  AddOutputFilterByType DEFLATE application/javascript application/json
  AddOutputFilterByType DEFLATE image/svg+xml
</IfModule>

<IfModule mod_brotli.c>
  AddOutputFilterByType BROTLI_COMPRESS text/html text/plain text/css
  AddOutputFilterByType BROTLI_COMPRESS application/javascript application/json
  AddOutputFilterByType BROTLI_COMPRESS image/svg+xml
</IfModule>
```

如果网站前面还有 CDN，应优先检查 CDN 是否已经压缩响应。源站和边缘节点的规则需要协调，避免无意义的重复处理，并确保 CDN 按 `Accept-Encoding` 正确协商和缓存。

## 如何检测压缩是否真正生效

不能只看控制面板中的“已开启”，应检查浏览器实际收到的响应。

使用 curl 测试 Brotli：

```bash
curl -I -H "Accept-Encoding: br" https://example.com/app.js
```

测试 Gzip：

```bash
curl -I -H "Accept-Encoding: gzip" https://example.com/app.js
```

重点查看这些响应头：

```http
Content-Type: application/javascript
Content-Encoding: br
Vary: Accept-Encoding
```

也可以使用：

```bash
curl --compressed -o /dev/null -s \
  -w "download=%{size_download} time=%{time_total}\n" \
  https://example.com/app.js
```

浏览器开发者工具的 Network 面板通常会显示资源的传输大小与解压后大小。测试时应分别检查 HTML、CSS、JavaScript，而不是只检测首页，因为 CDN 可能根据文件类型、状态码或资源大小应用不同规则。

性能评估不能只关注压缩率，还要对比：

- TTFB 是否因实时压缩而上升；
- 传输体积是否明显下降；
- CPU 使用率是否异常；
- 缓存命中率是否变化；
- 移动网络下的 LCP 等指标是否改善。

## 常见误区与部署建议

将 Brotli 级别调到最高，并不代表用户体验最佳。对频繁变化的动态 HTML，适中的实时压缩级别通常更稳妥；对带内容哈希、长期缓存的 CSS 和 JavaScript，则适合在构建阶段预压缩。

GitHub Pages 用户还需注意：仓库和 Jekyll 配置不能自由修改其 Web 服务器模块，也不能通过普通项目文件设置任意响应头。应以实际响应头为准，而不是假设平台一定返回某种编码。如果通过自有 CDN 代理自定义域名，可以在 CDN 层配置压缩，但要同时考虑 HTTPS、缓存失效和源站连接规则。

压缩优化的合理顺序是：先确认文本资源是否压缩，再比较 Brotli 与 Gzip 的传输收益，随后检查 CPU、缓存和核心网页指标。多数网站可采用“Brotli 优先、Gzip 回退、静态资源预压缩、动态内容使用中等级别”的方案。它不能保证排名变化，但能减少不必要的传输成本，并为真实用户性能和技术 SEO 提供更稳固的基础。

{% endraw %}
