---
title: "Hreflang标签配置与国际SEO指南"
description: "从语言与地区代码、双向引用到 canonical、站点地图和排错方法，系统讲解 hreflang 的正确配置流程与国际站 SEO 注意事项。"
---

# Hreflang标签配置与国际SEO指南

{% raw %}

## hreflang 解决什么问题

当网站针对不同语言或地区提供内容相近的页面时，搜索引擎需要判断应该向用户展示哪个版本。`hreflang` 用于声明页面之间的语言及地区关系，例如：

- 面向所有英语用户的英文页；
- 面向美国用户的英语页；
- 面向英国用户的英语页；
- 面向中国大陆用户的简体中文页。

它主要帮助搜索引擎选择更合适的页面版本，并理解这些相似页面属于同一内容体系。`hreflang` 不是跳转规则，也不会根据浏览器语言自动切换页面，更不能保证排名或收录。

典型适用场景包括：

1. 内容相同，但货币、配送范围或联系方式不同；
2. 页面主体相同，仅语言不同；
3. 同一种语言针对多个国家或地区提供本地化版本；
4. 国际站存在默认入口页或语言选择页。

如果每种语言的内容和目标受众完全不同，搜索引擎通常也能独立理解页面，此时是否配置应根据站点结构决定。

## 语言与地区代码怎么写

`hreflang` 的值通常由语言代码和可选的地区代码组成：

```text
语言代码
语言代码-地区代码
```

语言一般使用 ISO 639-1 两字母代码，地区一般使用 ISO 3166-1 Alpha-2 两字母代码。例如：

```text
zh-CN   简体中文，中国大陆
zh-TW   繁体中文，中国台湾
en      面向所有地区的英语
en-US   英语，美国
en-GB   英语，英国
de-DE   德语，德国
```

语言代码写在前面，地区代码写在后面。不要使用 `en-UK`，英国对应的地区代码是 `GB`；也不要只写 `US`，因为 `hreflang` 必须包含语言。

大小写通常不影响解析，但建议统一采用“语言小写、地区大写”的形式。需要表达中文书写体系时，也可以使用有效的脚本代码，例如：

```text
zh-Hans
zh-Hant
```

不要把语言代码当作页面实际内容的替代品。标记为 `fr-FR` 的页面应真正提供法语内容，而不是只有导航栏被翻译。

## 三种配置方式

Google 支持在 HTML、XML Sitemap 和非 HTML 文件的 HTTP 响应头中声明语言版本。通常选择一种方式完整实施即可，重复配置会增加维护和不一致风险。

### HTML head 标签

在每个语言版本的 `<head>` 中加入完整的版本集合：

```html
<link rel="alternate" hreflang="zh-CN"
      href="https://www.example.com/zh-cn/product/" />
<link rel="alternate" hreflang="en-US"
      href="https://www.example.com/en-us/product/" />
<link rel="alternate" hreflang="en-GB"
      href="https://www.example.com/en-gb/product/" />
<link rel="alternate" hreflang="x-default"
      href="https://www.example.com/product/" />
```

这组标签需要出现在中文、美国英文、英国英文和默认页面上，而不是只放在其中一个页面。

建议使用完整的绝对 URL，并保持协议、主机名、路径和结尾斜杠一致。标签必须位于有效的 `<head>` 区域，不能依赖用户交互后才插入。

### XML Sitemap

大型网站可以在站点地图中集中维护：

```xml
<url>
  <loc>https://www.example.com/en-us/product/</loc>
  <xhtml:link rel="alternate" hreflang="en-US"
    href="https://www.example.com/en-us/product/" />
  <xhtml:link rel="alternate" hreflang="en-GB"
    href="https://www.example.com/en-gb/product/" />
  <xhtml:link rel="alternate" hreflang="zh-CN"
    href="https://www.example.com/zh-cn/product/" />
</url>
```

根节点需要声明 XHTML 命名空间：

```xml
xmlns:xhtml="http://www.w3.org/1999/xhtml"
```

每个版本都应作为独立的 `<url>` 条目出现，并列出相同的备用页面集合。

### HTTP 响应头

PDF 等没有 HTML `<head>` 的文件可以使用：

```http
Link: <https://example.com/en/file.pdf>; rel="alternate"; hreflang="en",
      <https://example.com/de/file.pdf>; rel="alternate"; hreflang="de"
```

该方式需要在服务器或 CDN 层配置，并检查实际响应头是否正确返回。

## 双向引用、自引用与 x-default

完整的 `hreflang` 页面组需要遵守三个关键原则。

**第一，自引用。** 每个页面都要包含指向自己的声明。美国英语页面不仅要引用其他版本，也要声明自身为 `en-US`。

**第二，双向引用。** 如果页面 A 把页面 B 声明为备用版本，页面 B 也应引用页面 A。缺少返回链接时，搜索引擎可能忽略这组关系。

**第三，集合一致。** 同一组页面最好列出相同的语言版本。如果有 20 个市场页面，逐页手工修改很容易漏项，应由模板或内容管理系统根据页面映射表生成。

`x-default` 用于指定没有其他语言或地区匹配时的默认页面：

```html
<link rel="alternate" hreflang="x-default"
      href="https://www.example.com/language-selector/" />
```

它适合指向语言选择页、全球首页或默认市场页面。`x-default` 不是必填项，也不等同于英语版本。

## hreflang 与 canonical 如何配合

`canonical` 用于表达首选规范 URL，`hreflang` 用于表达合法的语言或地区变体，两者解决的问题不同。

一般情况下，每个可索引的本地化页面应使用自引用 canonical：

```html
<link rel="canonical"
      href="https://www.example.com/en-gb/product/" />
```

不要让所有语言页面都 canonical 到英文页。例如，中文页若 canonical 到英文页，同时又通过 `hreflang` 声明自己是中文版本，会产生矛盾信号，中文页也可能难以作为独立版本参与索引。

同时确认备用 URL：

- 返回 `200` 状态码；
- 未被 `robots.txt` 阻止抓取；
- 没有 `noindex`；
- 不指向重定向、404 或软 404 页面；
- canonical 没有指向页面组之外的其他 URL。

国家或语言自动跳转也要谨慎。若所有访问者和搜索引擎爬虫都被强制跳到同一地区，其他版本可能难以被发现。更稳妥的做法通常是保留可访问的独立 URL，提供切换入口，并在需要时显示地区建议，而不是无法取消的强制跳转。

## 实施流程与常见错误检查

上线前可以按以下步骤执行：

1. 建立 URL 映射表，按内容主题列出所有语言和地区版本；
2. 确认代码真实有效，页面语言与标注一致；
3. 选择 HTML、Sitemap 或 HTTP Header 中的一种主要实施方式；
4. 为每组页面生成自引用、双向引用和可选的 `x-default`；
5. 检查 canonical、索引指令、状态码及重定向；
6. 抓取全站，验证是否存在缺失页面或不一致集合；
7. 更新页面时同步维护已下线、合并或新增的语言版本。

常见错误包括：

- 把国家代码误当成语言代码；
- 只在首页配置，内页没有一一对应；
- A 引用 B，但 B 没有引用 A；
- 标签中的 URL发生跳转或返回错误状态；
- 移动端渲染后才生成标签，原始 HTML 中无法稳定读取；
- 不同页面输出了互相矛盾的版本集合；
- 页面已删除，但其他语言页仍然引用旧 URL。

可以通过查看网页源代码、检查实际 HTTP 响应头、验证 XML Sitemap，以及使用支持 hreflang 检查的网站爬虫进行核对。Google Search Console 的网址检查工具可辅助了解具体 URL 的抓取与规范化情况，但仍应结合服务器日志和全站抓取结果判断。

正确配置的核心不是标签数量，而是“页面映射真实、代码有效、关系完整、URL 可索引”。先建立稳定的国际站 URL 与内容结构，再用 `hreflang` 清晰描述各版本关系，才能减少维护错误，并帮助搜索引擎为不同地区用户选择更合适的页面。

{% endraw %}
