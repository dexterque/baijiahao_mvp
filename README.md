# 百家号内容 MVP

一个本地单用户 Streamlit 应用，用于完成这条最小闭环：

1. 导入竞品文章
2. 提取关键词
3. 同步深圳公安官网白名单官方资料
4. 使用 LLM 生成 5 个选题
5. 基于关键词和官方资料生成文章初稿
6. 基于草稿一键生成封面图
7. 做轻量事实校验
8. 导出 `.txt`、`.md` 或封面图，人工发布到百家号

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
   └─ fact_checker.py
```

## 启动步骤

### 1. 安装 Python 依赖

```bash
cd /Users/dexter/Code/baijiahao_mvp
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. 安装 Codex CLI

请先按你当前环境使用的 Codex CLI 安装方式完成安装，并确保命令可执行。

### 3. 安装 `openai-oauth`

常见做法是通过 Node.js 环境安装或直接用 `npx` 运行：

```bash
npx openai-oauth
```

如果你使用的是其他安装方式，请以对应版本说明为准。

### 4. 完成本地登录认证

先完成 Codex / OpenAI 本地登录，确保本机已经有可用认证状态。未登录或登录失效时，`openai-oauth` 一般无法正常代理请求。

### 5. 启动本地网关

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
```

你可以用下面的方式快速检查接口：

```bash
curl http://127.0.0.1:10531/v1/models
```

返回模型列表或 JSON 响应即可。

### 6. 启动项目

```bash
cp .env.example .env
uv run streamlit run app.py
```

启动顺序建议固定为：

1. 安装并登录 Codex
2. 完成本地认证
3. 启动 `openai-oauth`
4. 确认 `http://127.0.0.1:10531/v1/models` 可访问
5. 启动 Streamlit 项目

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

### 模型连接失败

现象：

- 页面提示无法连接本地网关

处理：

- 核对 `.env` 中的 `MODEL_BASE_URL`
- 确认网关地址不是官方 API 地址
- 确认 `MODEL_NAME` 与本地网关返回的模型一致

## 已知限制

- 仅支持单用户本地运行
- 不做百家号自动登录和自动发布
- 官方资料解析基于白名单页面结构和通用 HTML 规则，不保证覆盖所有栏目模板
- 轻量事实校验不是 claim 级逐句证据系统
- 如果官方资料本身不完整，草稿会倾向保守表达

## 后续建议

1. 增加更稳的官方栏目解析规则和定向 CSS 选择器
2. 增加草稿版本管理和人工修订对比
3. 增加定向政策摘要和结构化 facts 抽取质量提升
