# JobDone 任务完成通知工具 · 规范与设计 / Spec & Design (Bilingual)

> 语言约定 Language: 本文档包含中文与英文；代码注释全部使用英文。This document is bilingual (Chinese + English); all code comments will be in English.

## 背景与目标 / Background & Goals
- 目标：在 Shell 任务完成后统一触发通知（Webhook、Email、Desktop）。
- Goal: Send notifications when shell tasks finish via multiple channels.
- 典型用法：`my_job && jobdone ...`（成功后通知）或 `my_job; jobdone -e $? --on failure|always`。
- Typical usage: notify on success with `&&`; pass exit code for failure/always.

## 使用场景 / Use Cases
- 构建、测试、部署完成提醒；数据处理/备份脚本结束通知；训练/爬虫等长任务完成。
- Build/Test/Deploy completion; data/backup jobs; long-running tasks.

## 范围与非目标 / Scope & Non-Goals
- 范围：单机 CLI，支持多渠道通知、基础配置与打包。
- Scope: Single-machine CLI with multi-channel notifications and packaging.
- 非目标：不做任务编排/队列，不内置任务执行器。
- Non-goals: No orchestration/queue; not a job runner.

## 功能需求 / Functional Requirements
- 通知触发 Trigger: always (默认)、success、failure（配合 `--exit-code`）。
- 渠道 Channels: webhook、email、desktop（并发发送、结果汇总）。
- CLI 上下文 Context: job 名、title、message、exit_code、host、user、time。
- 配置与环境变量 Config & ENV: YAML + ENV + CLI 合并，CLI 优先。
- 退出码 Exit codes: 全部成功返回 0；任何失败返回非 0；参数/配置错误返回 2。

## 非功能需求 / Non-Functional Requirements
- 稳定：重试与退避；超时控制。
- Reliability: retries with backoff; timeouts.
- 安全：凭据来自 ENV；HTTPS/TLS；日志清洗敏感字段。
- Security: secrets via ENV; HTTPS/TLS; scrub tokens/passwords in logs.
- 便携：Linux 优先，后续支持 macOS/Windows。
- Portability: Linux first; macOS/Windows later.
- 性能：启动快，依赖少。
- Performance: fast startup, minimal deps.

## CLI 设计 / CLI Design
- 命令 Command: `jobdone` 或 `jobdone notify`。
- 参数 Options:
  - `-j, --job <string>` 任务名 / Job name.
  - `-t, --title <string>` 标题 / Title (default: "任务完成 / Job Done").
  - `-m, --message <string>` 消息 / Message；`--stdin` 从标准输入读取 / read from STDIN.
  - `-e, --exit-code <int>` 退出码 / Exit code (default 0).
  - `--on <success|failure|always>` 触发条件 / Trigger condition (default success).
  - `-c, --channel <list>` 渠道列表 / Channels, e.g. `webhook,email`.
  - Webhook: `--webhook-url <url>` (multi), `--header <k:v>` (multi).
  - Email: `--email-to <addr>` (multi), `--email-subject <string>`；SMTP 从 ENV/配置读取。
  - Desktop: 自动尝试 `notify-send` (Linux)，失败不影响其他渠道。
  - 通用 Common: `--timeout <sec>`, `--retries <n>`, `--backoff <sec>`, `--config <path>`, `-v/--verbose`, `--dry-run`。

## 环境变量与配置 / ENV & Config
- 环境变量 ENV:
  - `JOBDONE_CHANNELS="webhook,email"`
  - `JOBDONE_WEBHOOK_URLS="https://example.com/hook,https://hooks.slack..."`
  - `JOBDONE_SMTP_HOST`, `JOBDONE_SMTP_PORT`, `JOBDONE_SMTP_USER`, `JOBDONE_SMTP_PASS`, `JOBDONE_EMAIL_FROM`, `JOBDONE_EMAIL_TO`。
- 配置文件 YAML（默认路径 Default paths）：`~/.config/jobdone/config.yaml` 或项目 `.jobdone.yaml`；提供模板并提示拷贝到用户目录。
- 合并优先级 Merge precedence: CLI > ENV > YAML defaults。

### 配置示例 / YAML Example
```yaml
default:
  channels: [webhook, email]
  on: always
  retries: 2
  backoff: 2
webhook:
  urls:
    - https://hooks.slack.com/services/xxx
email:
  smtp_host: smtp.example.com
  smtp_port: 587
  from: noreply@example.com
  to:
    - me@example.com
```

## 架构设计 / Architecture
- 模块 Modules:
  - `cli`: 参数解析与入口 / CLI parsing & entrypoint.
  - `config`: 加载 ENV/YAML 并合并 / load & merge.
  - `template`（可选 optional）: 简易 Jinja2 渲染 title/message。
  - `channels`: `WebhookNotifier`, `EmailNotifier`, `DesktopNotifier`（统一接口 / common interface）。
  - `runner`: 并发发送、重试、结果汇总、日志 / parallel, retries, aggregation, logs.
- 接口 Interface: `Notifier.send(title, message, context) -> SendResult {ok: bool, error: str|null}`。
- 上下文 Context: `job`, `status`, `exit_code`, `host`, `user`, `time`。

## 运行流程 / Flow
1. 解析 CLI，加载配置，合并得到最终参数。
2. 判断触发条件（基于 `--on` 与 `exit_code`）。
3. （可选）渲染模板生成标题与消息。
4. 并发向各渠道发送，按策略重试，收集结果。
5. 汇总并决定退出码：全部成功 0；否则非 0。

## 重试与退出码 / Retry & Exit Codes
- 每渠道独立重试（固定/指数退避），到上限仍失败则记录。
- Exit codes: 0=all success; 1=any channel failed; 2=CLI/config error。

## 安全策略 / Security Practices
- Secrets 仅从 ENV 或安全存储读取；不写入日志。
- 使用 HTTPS/TLS；SMTP 采用 TLS/STARTTLS。
- 清洗日志中的 token/password 等敏感字段。

## 打包与发布 / Packaging & Release
- PyInstaller: `pyinstaller --onefile -n jobdone src/cli.py`。
- 产物 Artifact: 单文件可执行 `jobdone`（Linux），后续支持 macOS/Windows。
- 可提供 Makefile/pyproject 辅助构建。

## 测试计划 / Testing Plan
- 单元 Unit: CLI 解析、配置合并、模板渲染。
- 集成 Integration:
  - Webhook: 本地 HTTP server 验请求与重试。
  - Email: dev SMTP（如 MailHog），验证 TLS 与收件人。
  - Desktop: `notify-send` 存在与容错。
- 验收 Acceptance: 示例命令按预期触发并返回正确退出码。

## 示例 / Examples
- 成功完成 Success only:
  ```bash
  long_backup && jobdone -j backup -c webhook \
    --webhook-url https://example.com/hook -t "备份完成 / Backup Completed"
  ```
- 任意完成 Always (include failure):
  ```bash
  my_job; jobdone -j my_job -e $? --on always -c email
  ```
- 使用标准输入 STDIN as message:
  ```bash
  my_job && echo "任务已完成 / Task finished" | jobdone --stdin -j my_job -c desktop
  ```

## 约定 / Conventions
- 文档双语；代码注释与标识符以英文为主。
- Docs are bilingual; code comments will be in English.

## 迭代路线 / Roadmap
- v0: CLI、Webhook、Email、Desktop、基础配置与打包。
- v1: 模板化、并发与重试、结构化日志。
- v2: 更多渠道（Slack、Telegram）、跨平台安装脚本。

## 验收标准 / Acceptance Criteria
- CLI 支持上述参数与触发条件；多渠道并发发送；按重试策略执行；退出码准确；提供打包产物；示例命令可运行。
- CLI supports options & triggers; multi-channel concurrent send; retries; correct exit codes; packaged binary; examples run successfully.

### Webhook 负载 / Payload
- Content-Type: `application/json`
- JSON 结构：
```json
{
  "title": "通知标题",
  "message": "可选的文本消息",
  "context": {
    "job": "任务名",
    "status": "success|failure",
    "exit_code": 0,
    "host": "hostname",
    "user": "username",
    "timestamp": "ISO-8601 UTC",
    "source": "jobdone"
  }
}
```
- Headers：支持在 CLI 通过 `--header k:v`（可重复）或在 YAML 下 `webhook.headers` 配置。