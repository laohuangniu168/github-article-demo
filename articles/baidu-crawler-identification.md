---
title: "百度蜘蛛真假识别与日志验证方法"
description: "介绍如何从访问日志筛选疑似百度蜘蛛，并通过 PTR 反向解析、域名后缀校验和正向解析回验识别伪造请求，同时排查抓取状态码与代理配置问题。"
---

# 百度蜘蛛真假识别与日志验证方法

{% raw %}

## 为什么不能只看 User-Agent

百度蜘蛛访问网站时，通常会在 `User-Agent` 中包含 `Baiduspider`，常见形式类似：

```text
Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)
```

图片、视频等抓取程序的标识可能有所不同，因此日志筛选时可以先匹配 `Baiduspider`，不必把规则限定为某一条完整字符串。

但 `User-Agent` 是客户端自行发送的普通 HTTP 请求头，任何脚本都能伪造。下面这条命令就可以模拟表面上的百度蜘蛛请求：

```bash
curl -A "Mozilla/5.0 (compatible; Baiduspider/2.0)" https://example.com/
```

因此，看到 `Baiduspider` 只能说明这是“疑似百度蜘蛛”，不能据此直接加入服务器白名单，更不能绕过登录、鉴权或安全限制。可靠的判断需要结合：

1. 请求来源 IP；
2. IP 的 PTR 反向解析结果；
3. 解析所得主机名的正向回验；
4. 访问日志中的时间、状态码和抓取行为。

其中，双向 DNS 验证是识别真伪的核心步骤。

## 先从服务器日志提取疑似请求

Nginx 默认访问日志通常位于：

```text
/var/log/nginx/access.log
```

可以先筛选包含百度蜘蛛标识的记录：

```bash
grep -i "Baiduspider" /var/log/nginx/access.log
```

历史日志经过压缩时，可使用：

```bash
zgrep -i "Baiduspider" /var/log/nginx/access.log*.gz
```

一条典型记录可能是：

```text
203.0.113.25 - - [18/May/2025:10:20:31 +0800] "GET /article.html HTTP/1.1" 200 15342 "-" "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)"
```

这里的 IP 仅为文档示例地址，不代表百度真实网段。验证时应从自己的网站日志中提取实际来源 IP。

如果采用常见的 combined 日志格式，可以统计疑似请求的来源：

```bash
grep -i "Baiduspider" /var/log/nginx/access.log \
  | awk '{print $1}' \
  | sort | uniq -c | sort -nr
```

还可以按状态码统计：

```bash
grep -i "Baiduspider" /var/log/nginx/access.log \
  | awk '{print $9}' \
  | sort | uniq -c | sort -nr
```

需要注意，`awk` 中字段的位置取决于实际日志格式。如果站点自定义了 `log_format`，应先确认 `$remote_addr`、`$status`、`$request` 和 `$http_user_agent` 分别记录在哪里。

## 使用双向 DNS 验证来源 IP

验证过程不能只做一次反向解析，而应同时完成“反向解析”和“正向回验”。

### 第一步：查询 PTR 反向解析

假设从日志中获得待验证 IP：

```bash
dig +short -x 真实IP地址
```

也可以使用：

```bash
host 真实IP地址
```

如果返回一个主机名，应检查它是否以百度控制的域名后缀结束，例如：

```text
example.baidu.com.
```

判断后缀时必须包含域名边界。`crawler.baidu.com` 可以匹配 `.baidu.com`，但下面这些不能视为百度域名：

```text
baidu.com.example.net
fakebaidu.com
baidu.com.attacker.example
```

字符串中“出现 baidu.com”并不足够，必须确认最终注册域名及其后缀关系。若 PTR 没有结果、返回无关域名，或者查询持续失败，就不能仅凭 User-Agent 将其认定为真实百度蜘蛛。

### 第二步：对主机名做正向解析

获得主机名后，继续查询其 A 或 AAAA 记录：

```bash
dig +short A example.baidu.com
dig +short AAAA example.baidu.com
```

正向解析结果中必须包含最初日志里的 IP。完整逻辑如下：

```text
来源 IP
  → PTR 反查得到百度域名下的主机名
  → 主机名正向解析
  → 结果包含原始来源 IP
```

这个过程通常称为正向确认的反向 DNS，即 FCrDNS。它可以排除大量只伪造 User-Agent、只设置误导性 PTR，或者使用无关服务器发起的请求。

DNS 查询偶尔会因网络或解析器故障超时。单次失败不应直接作为永久封禁依据，可以间隔一段时间复查，并保存查询时间和结果。

## 用脚本批量验证日志 IP

当日志中有大量疑似请求时，可以使用 Python 批量执行双向验证：

```python
import ipaddress
import socket
import sys

ALLOWED_SUFFIXES = (".baidu.com", ".baidu.jp")

def verify(ip_text):
    ip = str(ipaddress.ip_address(ip_text))

    try:
        hostname = socket.gethostbyaddr(ip)[0].rstrip(".").lower()
    except (socket.herror, socket.gaierror, OSError):
        return False, "PTR 查询失败"

    if not any(hostname.endswith(suffix) for suffix in ALLOWED_SUFFIXES):
        return False, f"PTR 域名不匹配: {hostname}"

    try:
        results = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, None)
        }
    except socket.gaierror:
        return False, f"正向解析失败: {hostname}"

    normalized = {str(ipaddress.ip_address(item)) for item in results}

    if ip not in normalized:
        return False, f"正向解析未返回原 IP: {hostname}"

    return True, f"验证通过: {hostname}"

for value in sys.argv[1:]:
    ok, message = verify(value)
    print(value, "PASS" if ok else "FAIL", message)
```

保存为 `verify_baiduspider.py` 后运行：

```bash
python3 verify_baiduspider.py 需要验证的IP
```

实际生产环境可以先从日志中生成去重后的 IP 列表，再逐个检查。为了避免频繁查询 DNS，可以对验证结果设置合理缓存时间，但不建议把历史结果永久固化，因为搜索引擎的服务器地址和 DNS 记录可能变化。

也不应依赖网上流传的固定百度 IP 段列表。此类列表可能过期、不完整，或者缺少 IPv6 地址。固定网段可以作为辅助信息，不能替代实时双向解析。

## 代理、CDN 环境下如何确认真实 IP

如果网站使用 CDN、WAF、负载均衡或反向代理，源站日志中的 `$remote_addr` 可能是代理节点，而不是访客真实地址。此时直接对该 IP 做反查没有意义。

以 Nginx 为例，应只信任明确的代理地址范围，并从代理指定的请求头恢复来源 IP：

```nginx
set_real_ip_from 192.0.2.0/24;
real_ip_header X-Forwarded-For;
real_ip_recursive on;
```

上面的网段仍是示例，实际配置必须使用 CDN 或代理服务商官方公布的回源地址。不同平台使用的头部可能是 `X-Forwarded-For`、`CF-Connecting-IP` 或其他字段，应以服务商文档为准。

不能无条件信任公网客户端发送的 `X-Forwarded-For`。如果源站可以被直接访问，攻击者能够自行构造该请求头，制造任意来源 IP。较稳妥的做法是：

- 源站仅允许可信代理节点回源；
- `set_real_ip_from` 只配置官方代理地址段；
- 日志同时保留代理 IP、还原后的客户端 IP和 User-Agent；
- 使用还原后的可信来源 IP执行 DNS 验证。

修改真实 IP 配置后，还应检查 Nginx 配置并平滑重载：

```bash
nginx -t
nginx -s reload
```

## 验真之后还要检查抓取结果

确认请求来源真实，只说明访问者确实可能属于百度抓取系统，并不代表页面已经收录，也不代表一定获得排名。还要继续检查日志中的请求路径和 HTTP 状态码。

重点关注以下情况：

- `200`：页面正常返回，但仍不等于已收录；
- `301`、`302`：检查是否存在多次跳转、循环跳转或错误目标；
- `304`：缓存验证正常时常见；
- `403`：可能被权限控制、防火墙或防盗链规则拦截；
- `404`、`410`：确认链接是否失效，以及站内是否仍在引用；
- `429`：限速策略可能过严；
- `500`、`502`、`503`、`504`：检查应用、上游服务和服务器负载。

还应核对 `robots.txt` 是否可访问、重要页面是否被禁止抓取，以及安全软件是否只因为 User-Agent、请求频率或无 Cookie 行为而拦截蜘蛛。不要为了“放行蜘蛛”关闭整站安全策略，更不要仅根据 User-Agent 设置特权访问。

稳妥的排查顺序是：先在原始日志中找到请求，再确认日志记录的是真实客户端 IP，随后完成 PTR 反查和正向回验，最后结合状态码、URL 与响应情况判断抓取是否正常。这样既能识别大多数伪造百度蜘蛛，也能发现真实抓取请求被 CDN、限速或服务器配置误伤的问题。

{% endraw %}
