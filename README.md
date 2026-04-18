# 百家号内容 MVP

一个本地单用户 Streamlit 应用，用于完成这条最小闭环：

1. 导入竞品文章
2. 提取关键词
3. 同步深圳公安官网白名单官方资料
4. 使用 LLM 生成 5 个选题
5. 基于关键词和官方资料生成文章初稿
6. 基于草稿一键生成封面图
7. 做轻量事实校验
8. 导出 `.txt`、`.md`、封面图，或一键同步到百家号草稿箱

## 技术栈

- Streamlit
- SQLite
- jieba
- requests + BeautifulSoup
- OpenAI Python SDK

## 目录结构

```text
baijiahao_mvp/
├─ app.py
├─ requirements.txt
├─ .env.example
├─ README.md
├─ data/
│  └─ baijiahao.db
├─ exports/
├─ prompts/
│  ├─ topic_prompt.txt
│  ├─ article_prompt.txt
│  └─ fact_check_prompt.txt
├─ scripts/
│  ├─ sync_draft_to_baijiahao.py
│  └─ run_scheduled_pipeline.py
└─ modules/
   ├─ db.py
   ├─ utils.py
   ├─ article_importer.py
   ├─ keyword_extractor.py
   ├─ image_generator.py
   ├─ official_parser.py
   ├─ official_sync.py
   ├─ llm_client.py
   ├─ topic_generator.py
   ├─ draft_generator.py
   ├─ fact_checker.py
   └─ wechatsync_client.py
```

## 启动步骤

### 1. 安装 Python 依赖

```bash
cd /Users/dexter/Code/baijiahao_mvp
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. 安装 Wechatsync CLI

用于把本地草稿同步到百家号草稿箱：

```bash
npm install -g @wechatsync/cli
```

如果你不想全局安装，也可以不配这一步，项目会优先尝试 `wechatsync`，找不到时自动回退到：

```bash
npx -y @wechatsync/cli
```

### 3. 安装 Chrome 扩展并登录百家号

先安装 Wechatsync Chrome 扩展，并确保浏览器里已经登录百家号后台。CLI 只负责发起同步，真正的平台登录态来自浏览器扩展。

### 4. 安装 Codex CLI

请先按你当前环境使用的 Codex CLI 安装方式完成安装，并确保命令可执行。

### 5. 安装 `openai-oauth`

常见做法是通过 Node.js 环境安装或直接用 `npx` 运行：

```bash
npx openai-oauth
```

如果你使用的是其他安装方式，请以对应版本说明为准。

### 6. 完成本地登录认证

先完成 Codex / OpenAI 本地登录，确保本机已经有可用认证状态。未登录或登录失效时，`openai-oauth` 一般无法正常代理请求。

### 7. 启动本地网关

确保本地 OpenAI-compatible 网关启动，并监听在：

```text
http://127.0.0.1:10531/v1
```

默认环境变量如下：

```env
MODEL_BASE_URL=http://127.0.0.1:10531/v1
MODEL_API_KEY=dummy
MODEL_NAME=gpt-5.4
IMAGE_BASE_URL=http://127.0.0.1:10531/v1
IMAGE_API_KEY=dummy
IMAGE_MODEL_NAME=gpt-image-1
DATABASE_PATH=data/baijiahao.db
WECHATSYNC_BIN=
WECHATSYNC_PLATFORM=baijiahao
WECHATSYNC_TIMEOUT_SECONDS=300
WECHATSYNC_TOKEN=
COVER_PROVIDER=local
COVER_LIBRARY_DIR=assets/covers
```

你可以用下面的方式快速检查接口：

```bash
curl http://127.0.0.1:10531/v1/models
```

返回模型列表或 JSON 响应即可。

### 8. 启动项目

```bash
cp .env.example .env
uv run streamlit run app.py
```

启动顺序建议固定为：

1. 安装并登录百家号与 Wechatsync Chrome 扩展
2. 安装并登录 Codex
3. 完成本地认证
4. 启动 `openai-oauth`
5. 确认 `http://127.0.0.1:10531/v1/models` 可访问
6. 启动 Streamlit 项目

## 页面说明

### 页面 1：竞品文章导入

- 手动录入文章
- CSV 批量导入
- 查看文章列表

CSV 至少支持这些列名：

- `title`
- `content`
- `source_name`
- `source_url`
- `publish_time`

### 页面 2：关键词库

- 从文章重建关键词
- 展示词频、分类、来源文章数
- 支持搜索和分类筛选
- 自动生成时的主关键词/相关关键词来自此关键词库，需先导入竞品文章并重建关键词

### 页面 3：官方资料同步

- 初始化白名单来源
- 一键同步官方资料
- 查看同步结果和文档详情

### 页面 4：选题与出稿

- 选择主关键词
- 调用 LLM 生成 5 个选题
- 匹配相关官方资料
- 生成并保存文章草稿
- 基于草稿标题和正文一键生成封面图
- 下载或保存 PNG 封面图

### 页面 5：轻量校验

- 对草稿做高风险表述检查
- 检查是否引用到官方资料
- 识别可能写死时间、入口、条件但缺少支撑的句子
- 导出 `.txt` / `.md`
- 一键同步到百家号草稿箱

## 官方来源白名单

第一版默认写死以下白名单来源：

- 深圳市公安局官网首页
- 户政知识库
- 户籍迁入相关公开入口
- 申请材料相关公开入口
- 通知公告相关公开入口

当前只允许白名单来源进入官方资料库，不做复杂来源后台管理。

## 常见问题

### 本地网关未启动

现象：

- 生成选题报连接失败
- 生成草稿时报连接失败

处理：

- 先启动 `openai-oauth`
- 再检查 `http://127.0.0.1:10531/v1/models` 是否可访问

### 登录态失效

现象：

- 网关可启动，但模型调用返回认证错误

处理：

- 重新完成本地登录
- 重启网关再试

### 官方资料同步失败

现象：

- 某些页面返回超时或解析失败

处理：

- 稍后重试
- 检查网络是否能访问 `ga.sz.gov.cn`
- 某个详情页失败不会中断整批同步

### 百家号草稿箱同步失败

现象：

- 页面提示 `wechatsync` 执行失败
- 提示扩展未连接或平台未登录

处理：

- 确认 Chrome 扩展已安装并启用
- 确认浏览器里已登录百家号后台
- 如果没有全局安装 CLI，可先试 `npx -y @wechatsync/cli platforms`
- 如需自定义命令路径，可在 `.env` 中设置 `WECHATSYNC_BIN`

### 模型连接失败

现象：

- 页面提示无法连接本地网关

处理：

- 核对 `.env` 中的 `MODEL_BASE_URL`
- 确认网关地址不是官方 API 地址
- 确认 `MODEL_NAME` 与本地网关返回的模型一致

## 已知限制

- 仅支持单用户本地运行
- 不做百家号自动登录和自动正式发布，只同步到草稿箱
- 官方资料解析基于白名单页面结构和通用 HTML 规则，不保证覆盖所有栏目模板
- 轻量事实校验不是 claim 级逐句证据系统
- 如果官方资料本身不完整，草稿会倾向保守表达

## 定时同步草稿箱

如果你只是希望“定时推到百家号草稿箱”，可以直接配系统定时任务调用：

```bash
uv run python scripts/sync_draft_to_baijiahao.py --checked-only --generate-cover
```

示例 `crontab`：

```bash
*/30 * * * * cd /Users/dexter/Code/baijiahao_mvp && /usr/bin/env bash -lc 'source .venv/bin/activate && uv run python scripts/sync_draft_to_baijiahao.py --checked-only --generate-cover'
```

这会优先选择最近一篇 `fact_status=checked` 的草稿，同步到百家号草稿箱。

## 定时生成内容并推送草稿箱

如果你希望“自动生成一篇新内容，然后自动推到百家号草稿箱”，可以使用：

```bash
uv run python scripts/run_scheduled_pipeline.py --rebuild-keywords
```

> 注意：该命令默认会从关键词库里自动选主关键词和相关关键词，建议先导入竞品文章并执行关键词重建。若你希望固定主关键词，可加 `--main-keyword 入户`。

常见参数：

- `--main-keyword 入户`：固定主关键词，不走自动选择
- `--related-keyword-count 6`：自动附带更多相关词
- `--topic-index 0`：默认选第 1 个选题
- `--sync-official`：运行前先同步官方资料
- `--official-detail-limit 10`：官方资料同步深度
- `--strict-fact-check`：只允许 `pass` 推送，`warning` 也拦住
- `--skip-cover-generation`：跳过自动封面图生成
- `--cover-provider local`：封面图生成器，默认从本地图库随机选图，可选 local、met、auto、openai
- `--cover-size 1536x1024`：设置封面图尺寸
- `--cover-quality medium`：设置封面图质量
- `--skip-sync`：只生成草稿，不推送百家号

推荐的定时任务示例：

```bash
0 9,15,21 * * * cd /Users/dexter/Code/baijiahao_mvp && /usr/bin/env bash -lc 'mkdir -p logs && source .venv/bin/activate && uv run python scripts/run_scheduled_pipeline.py --rebuild-keywords >> logs/pipeline.log 2>&1'
```

如果你希望每天先拉一轮官方资料，再生成并推送：

```bash
0 8 * * * cd /Users/dexter/Code/baijiahao_mvp && /usr/bin/env bash -lc 'mkdir -p logs && source .venv/bin/activate && uv run python scripts/run_scheduled_pipeline.py --sync-official --rebuild-keywords >> logs/pipeline.log 2>&1'
```

建议：

- 定时任务运行时，确保 `openai-oauth` 已经在本机持续运行
- 确保浏览器 Wechatsync 扩展在线，且百家号登录态未失效
- 流水线默认会从 `assets/covers/` 本地图库随机选择封面图，并复制一份到 `exports/covers/`
- 如果你希望自动拉取公版艺术作品封面，可以用 `--cover-provider met`
- 如果你想继续尝试在线生图，可把 `--cover-provider` 改成 `openai` 或 `auto`
- 初期先不要开太高频，建议每天 1 到 3 次，人工观察几天再放大

## 后续建议

1. 增加更稳的官方栏目解析规则和定向 CSS 选择器
2. 增加草稿版本管理和人工修订对比
3. 增加定向政策摘要和结构化 facts 抽取质量提升
