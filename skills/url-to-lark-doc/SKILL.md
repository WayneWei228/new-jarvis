---
name: url-to-lark-doc
description: "从多个 URL 抓取内容（源码、文章、创意作品等），进行分析整理，然后创建结构化的飞书云文档。支持 OpenProcessing、CodePen、通用网页等来源。当用户提供一组 URL 并要求整理、分析、归档到飞书文档时使用；当用户说"把这些网址内容整理到飞书""帮我把这些链接的内容导入飞书文档"时触发。"
metadata:
  requires:
    bins: ["lark-cli", "curl"]
---

# URL to Lark Doc

从 URL 列表抓取内容 → 分析整理 → 创建飞书云文档。

**前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md) 了解 lark-cli 认证和身份切换。

## 工作流

### Step 1: 解析 URL 并分类

从用户输入中提取所有 URL，按平台分类：

| 平台 | URL 特征 | 获取策略 |
|------|---------|---------|
| OpenProcessing | `openprocessing.org/sketch/<id>` | API 直取（最可靠） |
| CodePen | `codepen.io/<user>/pen/<id>` | 搜索引擎降级（受 Cloudflare 限制） |
| GitHub | `github.com/...` | `gh` CLI 或 WebFetch |
| 通用网页 | 其他 | WebFetch 直取，失败则搜索降级 |

详细获取策略见 [references/url-fetch-strategies.md](references/url-fetch-strategies.md)。

### Step 1.5: 判断是否需要截图

对于 **视觉/美术类** 网站（包括但不限于）：

| 类型 | 示例平台 |
|------|---------|
| 交互叙事 | The Pudding、Flourish、Scrollytelling 作品 |
| 创意编程 | OpenProcessing、CodePen、p5.js 作品 |
| 设计作品集 | Behance、Dribbble、Cargo |
| 数据可视化 | D3.js 作品、Observable notebooks |
| 艺术/插画 | 个人艺术网站、在线画廊 |
| 交互设计 | 有丰富视觉表现的产品页、Landing Page |

**必须使用 headless Chrome 截图并插入飞书文档**，因为这类作品的视觉呈现是赏析的核心。

```bash
# 使用 headless Chrome 截图（macOS）
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu \
  --screenshot=/path/to/screenshot.png \
  --window-size=1440,1080 \
  --virtual-time-budget=10000 \
  "<URL>"
```

截图后通过 `lark-cli docs +media-insert` 插入文档末尾：

```bash
lark-cli docs +media-insert --as user \
  --doc <doc_id> \
  --file screenshot.png \
  --type image --align center \
  --caption "<图片描述>"
```

**注意**：
- `+media-insert` 的 `--file` 必须是当前目录下的相对路径，需先将截图复制到项目目录
- `+media-insert` 只能插入到文档末尾
- `--virtual-time-budget=10000` 让 JS 有足够时间渲染动态内容
- 截图完成后清理临时文件

### Step 2: 并行抓取内容

对所有 URL 并行发起抓取，最大化效率：

**OpenProcessing**（使用脚本或直接 curl）：
```bash
# 元数据
curl -sL "https://openprocessing.org/api/sketch/<ID>"
# 源码
curl -sL "https://openprocessing.org/api/sketch/<ID>/code"
```

**CodePen**（搜索降级）：
```
WebFetch("https://html.duckduckgo.com/html/?q=codepen+<user>+<penId>")
```

**通用网页**：
```
WebFetch(url, prompt="提取页面的完整内容，包括标题、正文、代码等")
```

抓取失败时记录失败原因，继续处理其他 URL，最终在文档中标注无法获取的内容。

### Step 3: 分析与结构化

对每个成功获取的内容进行分析，提取：

- **基础信息**：标题、作者、来源、创建日期、许可证
- **内容主体**：完整源码 / 文章正文 / 核心内容
- **技术分析**（适用于代码类内容）：
  - 架构设计（类/模块划分）
  - 核心算法和技术要点
  - 配置参数说明
- **跨作品对比**（多个同类内容时）：维度化对比表

### Step 4: 确认 lark-cli 就绪

```bash
lark-cli config show
```

如果未配置，运行 `lark-cli config init --new`（后台执行，提取授权链接给用户）。

如果需要 user 身份写文档：
```bash
lark-cli auth login --domain docs
```

### Step 5: 创建飞书文档

使用 Lark-flavored Markdown 创建结构化文档。内容较长时分段创建：

```bash
# 创建文档（含前言 + 第一部分）
lark-cli docs +create --as user --title "<文档标题>" --markdown '<内容>'

# 追加后续部分（通过临时文件传入长内容）
lark-cli docs +update --as user --doc <doc_id> --mode append --markdown @<file.md>
```

**长内容处理**：将 markdown 写入项目目录内的临时 `.md` 文件，用 `@filename.md` 传入，完成后删除临时文件。

**注意**：`--markdown @<file>` 要求文件路径是当前目录下的相对路径。

### Step 6: 输出结果

向用户返回：
1. 文档链接
2. 内容摘要（成功获取了哪些、哪些失败）
3. 文档结构概览

## 文档排版规范

创建飞书文档时遵循以下排版原则：

- **开头**：用 `<callout>` 总结文档主旨
- **每个作品/内容**独立一个 `##` 章节
- **基础信息**：用 `<callout emoji="📋" background-color="light-green">` 列表展示
- **源码**：用围栏代码块 + 语言标注
- **技术分析**：用 `<callout emoji="💡" background-color="light-yellow">` 高亮
- **多作品对比**：用 Markdown 表格
- **尾部链接**：用 `<callout emoji="🔗" background-color="light-purple">` 汇总原始链接
- **章节间**：用 `---` 分割线分隔

完整的 Lark-flavored Markdown 语法见 [`../lark-doc/references/lark-doc-create.md`](../lark-doc/references/lark-doc-create.md)。

## 权限

| 操作 | 所需 scope |
|------|-----------|
| 创建文档 | `docx:document:create` |
| 更新文档 | `docx:document:write_only` |
| 上传媒体 | `drive:file:upload` |
