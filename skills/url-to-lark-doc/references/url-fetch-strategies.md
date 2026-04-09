# URL 内容获取策略

不同平台的内容获取方式差异很大，按平台选择策略。

## OpenProcessing

OpenProcessing 主站受 Cloudflare 保护，无法直接抓取。使用其公开 API：

```bash
# Step 1: 获取 sketch 元数据（标题、描述、引擎、模式等）
curl -sL "https://openprocessing.org/api/sketch/<SKETCH_ID>"

# Step 2: 获取完整源码（返回 JSON 数组，每个元素包含 codeID、code、title）
curl -sL "https://openprocessing.org/api/sketch/<SKETCH_ID>/code"
```

从 URL 中提取 SKETCH_ID：`https://openprocessing.org/sketch/2768289` → ID = `2768289`

元数据返回字段：
- `title` — 作品标题
- `description` — 作品描述
- `mode` — 运行模式（p5js / html）
- `engineURL` — 引擎 CDN 地址
- `license` — 许可证
- `createdOn` / `updatedOn` — 创建/更新时间
- `userID` — 作者 ID

代码返回字段（数组）：
- `code` — 完整源码字符串
- `title` — 文件名（如 mySketch.js、style.css、index.html）
- `orderID` — 文件排序

## CodePen

CodePen 全站受 Cloudflare 保护（403/Challenge），所有 URL 模式均被拦截：
- 主页：`codepen.io/<user>/pen/<id>`
- 嵌入：`codepen.io/<user>/embed/<id>`
- 全屏：`cdpn.io/<user>/fullpage/<id>`
- 后缀：`.js` / `.css`
- oEmbed API

**降级策略**：通过搜索引擎获取基础信息
```bash
# 使用 DuckDuckGo HTML 版搜索（需 follow redirect 到 html.duckduckgo.com）
WebFetch("https://html.duckduckgo.com/html/?q=codepen+<user>+<penId>")
```
可获取：标题、简短描述。无法获取源码。

如果有 Tavily skill 可用，优先使用 `tavily_search` 和 `tavily_extract` 获取更完整的内容。

## 通用网页

1. 优先使用 `WebFetch` 直接获取
2. 如果返回 403 或 Cloudflare Challenge，尝试搜索引擎降级
3. 对于 GitHub 链接，使用 `gh` CLI 代替

## 内容提取优先级

1. **平台 API**（如 OpenProcessing API）— 最可靠，返回结构化数据
2. **WebFetch 直接抓取** — 适用于无反爬的站点
3. **Tavily extract** — 适用于 JS 渲染的页面
4. **搜索引擎降级** — 仅能获取标题和摘要，作为最后手段
