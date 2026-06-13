# astrbot_plugin_bilibili_assistant

面向 B站账号评论区运营的 AstrBot 插件。它用于读取评论、生成回复草稿、人工确认后发布、监听新评论、记录审计日志，并提供 WebUI Dashboard 进行扫码登录和状态查看。

## 项目状态

- 许可证：MIT License，见 [LICENSE](LICENSE)。
- AI 使用声明：本项目代码、文档和测试由用户提出需求，并在 AI 编程助手辅助下复制、整理、改写和生成，见 [AI_USAGE.md](AI_USAGE.md)。
- 安全说明：部署前请阅读 [SECURITY.md](SECURITY.md)，不要把 B站 Cookie、账号凭证或隐私数据提交到仓库。
- 当前版本：`v0.2.13`。

本插件默认采用安全策略：`dry_run=true`、`auto_reply_enabled=false`、`require_confirmation=true`。也就是说，首次安装后不会自动真实发布评论，需要你明确关闭演练模式并完成确认流程。

## 功能概览

- 读取 B站视频信息和最新评论
- 针对评论生成回复草稿
- 支持人工编辑、拒绝、确认发送
- 支持评论监听任务：只通知、生成草稿、自动回复
- 支持 B站扫码登录，自动写入 Cookie
- 支持 WebUI Dashboard 查看状态、草稿、监听任务和日志
- 支持点赞、删除自己发布的评论
- 支持黑名单、敏感词、频率限制、重复回复检查
- 支持 SQLite 审计日志和 CSV 导出
- 支持命令开关：`/bilicomment_on`、`/bilicomment_off`、`/bilicomment_status`

## 安装

将插件目录放入 AstrBot 插件目录，例如：

```text
data/plugins/astrbot_plugin_bilibili_assistant
```

安装依赖：

```bash
pip install -r requirements.txt
```

依赖包括：

```text
httpx
aiosqlite
qrcode
```

然后在 AstrBot WebUI 中重载插件。若从 zip 安装，建议先卸载旧版本，再安装新版 zip，避免旧目录结构残留。

## 快速开始

推荐首次使用流程：

```text
/bilicomment_status
/bilihelp
/bili_status
/bili_version
/bili_ai_check
/bili_video BV1xxxxxxx
/bili_comments BV1xxxxxxx 5
/bili_ai_rpid BV1xxxxxxx 123456 cute
/bili_ai_reply cute 太好看了，期待下一期
/bili_draft BV1xxxxxxx 123456 friendly
/bili_pending
/bili_send draft_abcd1234efgh
```

首次默认 `dry_run=true`，所以 `/bili_send` 不会真的发到 B站，只会写入演练日志并展示将发送的内容。

确认流程建议：

```text
/bili_dryrun off
/bili_send draft_abcd1234efgh
/bili_confirm a1b2c3
```

如果配置中 `require_confirmation=true`，真实发送前会生成 5 分钟有效的确认码。

## 配置说明

配置文件由 `_conf_schema.json` 注册，可在 AstrBot WebUI 插件配置中编辑。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 插件配置级总开关。运行中也可以用 `/bilicomment_on/off` 临时开关。 |
| `bilibili_cookie` | 空 | B站登录 Cookie。可手动填写，也可在 Dashboard 中扫码自动写入。 |
| `default_check_interval_seconds` | `300` | 新建监听任务时的默认检查间隔，最低建议 60 秒。 |
| `max_replies_per_hour` | `5` | 每小时真实回复上限。dry-run 不计入真实回复上限。 |
| `max_replies_per_day` | `30` | 每日真实回复上限。 |
| `auto_reply_enabled` | `false` | 是否允许自动回复。即使开启，也会经过安全检查。 |
| `require_confirmation` | `true` | 真实发布或删除前是否需要确认码。 |
| `reply_style` | `friendly` | 草稿风格，支持 `friendly`、`official`、`cute`、`concise`、`humorous`。 |
| `blocked_keywords` | 内置敏感词 | 回复文本命中后会被安全检查拦截。 |
| `allowed_video_list` | `[]` | 允许监听的视频 BV 号列表；空列表表示不限制。 |
| `admin_user_ids` | `[]` | 允许操作发布、草稿、监听、黑名单等命令的 AstrBot 用户 ID。空列表表示所有人可操作，不建议正式环境这样用。 |
| `blacklisted_user_ids` | `[]` | B站用户 mid 黑名单。命中后只进入人工审核，不自动回复。 |
| `dry_run` | `true` | 演练模式。开启时不会真实发布、点赞或删除。 |
| `chat_provider_id` | 空 | 指定生成草稿使用的 AstrBot 模型提供商 ID；空值使用默认模型。 |

Cookie 是登录凭据，等同账号权限。不要在群聊中发送，不要提交到仓库，不要发给他人。建议使用专门的 B站运营号。

## WebUI Dashboard

插件提供 `pages/dashboard/` 页面。安装并重载后，在 AstrBot WebUI 的插件详情页进入 Dashboard。

Dashboard 支持：

- 查看插件启用状态、Cookie 状态、dry-run 状态、今日日志数
- 查看当前 B站登录账号
- 生成 B站扫码登录二维码
- 扫码确认后自动保存 `bilibili_cookie`
- 查看待审核草稿
- 查看监听任务
- 查看最近日志

扫码登录流程：

1. 打开插件 Dashboard。
2. 点击“生成二维码”。
3. 使用 B站客户端扫码。
4. 在 B站客户端确认登录。
5. Dashboard 显示扫码成功后，插件会在后端保存 Cookie。
6. 执行 `/bili_status` 或刷新 Dashboard 验证账号状态。

扫码登录使用 B站网页登录二维码接口。若二维码过期、接口变动或账号触发风控，可回到插件配置中手动填写 Cookie。

## 命令详解

### `/bilicomment_on`

启用当前运行实例中的插件功能。

```text
/bilicomment_on
```

说明：

- 只影响当前运行实例中的 `self.enabled` 状态。
- 不会自动修改 `_conf_schema.json` 或配置文件里的 `enabled` 默认值。
- 若配置了 `admin_user_ids`，只有管理员可执行。

### `/bilicomment_off`

关闭当前运行实例中的插件功能。

```text
/bilicomment_off
```

说明：

- 关闭后，大多数 `/bili_*` 功能会提示先启用插件。
- 已存在的监听调度器不会主动发真实评论，因为命令入口和自动回复条件都受安全策略限制。
- 若配置了 `admin_user_ids`，只有管理员可执行。

### `/bilicomment_status`

查看插件开关、Cookie、dry-run、自动回复、确认机制和今日日志数量。

```text
/bilicomment_status
```

适合快速检查插件是否启用，不会请求 B站账号信息。

### `/bili_status`

检查插件状态和 B站登录状态。

```text
/bili_status
```

返回内容通常包括：

- 插件是否启用
- Cookie 是否已配置
- `dry_run` 状态
- `auto_reply` 状态
- `require_confirmation` 状态
- 今日日志数量
- B站账号昵称和 mid

注意：

- 如果 Cookie 失效，会提示重新获取 Cookie。
- 如果 Cookie 缺少 `SESSDATA` 或 `bili_jct`，读取或发布能力会受影响。

### `/bili_version`

查看 AstrBot 当前实际加载的插件版本和插件目录。

```text
/bili_version
```

排错说明：

- 如果返回的版本不是 README 或 zip 包标注的新版本，说明 AstrBot 仍在加载旧插件目录或旧 zip。
- 如果 `/bili_comments` 仍返回旧版错误文案，先执行本命令确认实际加载版本。
- 卸载旧包后建议停止 AstrBot 进程，再删除残留插件目录并重新安装新版 zip。

### `/bili_bind`

提示用户到 WebUI 配置或 Dashboard 中填写 Cookie。

```text
/bili_bind
```

说明：

- 这个命令不会在聊天中接收 Cookie。
- 设计上避免用户把敏感 Cookie 直接发到群聊或私聊记录中。

### `/bili_video <BV号>`

查询 B站视频基本信息。

```text
/bili_video BV1xxxxxxx
```

参数：

- `<BV号>`：B站视频 BV 号。

返回内容：

- 视频标题
- `aid`
- `bvid`
- UP 主名称
- 评论区参数提示：视频评论区通常 `oid=aid`、`type=1`

注意：

- 后续评论读取和回复都依赖视频 `aid`。
- 如果视频不存在、被删除或不可访问，会返回 B站接口错误提示。

### `/bili_comments <BV号> [数量]`

拉取某个视频的最新评论摘要。

```text
/bili_comments BV1xxxxxxx
/bili_comments BV1xxxxxxx 5
```

参数：

- `<BV号>`：B站视频 BV 号。
- `[数量]`：可选，显示数量，范围会被限制在 1 到 10。

返回内容：

- 评论层级：`主评论` 或 `评论回复`
- 评论用户昵称
- 用户 mid
- 评论 rpid
- 楼中楼回复会显示 `root` 和 `parent`
- 点赞数
- 评论内容摘要

说明：

- 拉取到的评论会写入本地 `seen_comments` 表。
- `/bili_draft` 需要通过 `rpid` 找到目标评论，建议先执行本命令。
- `主评论` 是视频下的一级评论；`评论回复` 是某条评论下面的楼中楼回复。
- 对 `评论回复` 生成草稿时，插件会保留其所属主评论 `root`，发送时会回复到目标 `rpid`，不会误当成一级评论处理。

### `/bili_draft <BV号> <rpid> [风格]`

针对指定评论生成回复草稿。

```text
/bili_draft BV1xxxxxxx 123456
/bili_draft BV1xxxxxxx 123456 friendly
/bili_draft BV1xxxxxxx 123456 official
```

参数：

- `<BV号>`：目标视频 BV 号。
- `<rpid>`：目标评论 ID，可从 `/bili_comments` 返回中获取。
- `[风格]`：可选，支持 `friendly`、`official`、`cute`、`concise`、`humorous`。

执行流程：

1. 获取视频信息。
2. 查找目标评论。
3. 对源评论做安全标记。
4. 调用 AstrBot 模型生成回复草稿。
5. 对回复文本做安全检查。
6. 保存草稿到 SQLite。

返回内容：

- `draft_id`
- 目标层级：`主评论` 或 `评论回复`
- 安全标记
- 草稿内容
- 发送命令提示
- 修改命令提示

注意：

- 如果模型调用失败，会使用规则模板兜底生成草稿。
- 生成草稿不等于真实发送。

### `/bili_ai_rpid <BV号> <rpid> [风格]`

根据视频 BV 号和评论 `rpid` 调用 AI 生成回复，只在聊天内展示文本，不保存草稿，也不会发布到 B站。

```text
/bili_ai_rpid BV1xxxxxxx 123456
/bili_ai_rpid BV1xxxxxxx 123456 cute
/bili_ai_rpid BV1xxxxxxx 123456 official
```

参数：

- `<BV号>`：目标视频 BV 号。
- `<rpid>`：目标评论 ID，可通过 `/bili_comments <BV号> [数量]` 获取。
- `[风格]`：可选，支持 `friendly`、`official`、`cute`、`concise`、`humorous`。

说明：

- 适合先预览 AI 会怎么回，不进入待审核草稿列表。
- 如果确认要保存为草稿并后续发送，请使用 `/bili_draft <BV号> <rpid> [风格]`。
- 返回内容会显示目标评论层级、原评论摘要、生成来源、安全检查结果和安全标记。

### `/bili_ai_reply [风格] <需要回复的内容>`

不依赖 B站评论 ID，直接根据输入内容调用 AI 生成一条评论区回复草稿。

```text
/bili_ai_reply 太好看了，期待下一期
/bili_ai_reply cute 太好看了，期待下一期
/bili_ai_reply official 这个地方是不是讲错了？
```

参数：

- `[风格]`：可选，支持 `friendly`、`official`、`cute`、`concise`、`humorous`。
- `<需要回复的内容>`：用户评论、私信片段或你想回复的原文。

说明：

- 插件会优先使用当前聊天会话的模型；如果配置了 `chat_provider_id`，则优先使用配置指定的模型。
- 生成结果只会作为聊天内草稿展示，不会自动发布到 B站。
- 生成后仍会经过安全检查，提示是否通过以及命中的安全标记。
- 如果 AI 调用失败，插件会退回固定模板，并在返回内容里显示失败原因。

### `/bili_ai_check`

测试插件能否调用 AstrBot 当前会话模型。

```text
/bili_ai_check
```

说明：

- 如果返回“AI 调用成功”，说明 `/bili_ai_reply` 和 `/bili_draft` 可以使用模型生成。
- 如果返回“AI 调用失败”，生成回复会退回固定模板，需要检查 AstrBot 模型配置或插件 `chat_provider_id`。

### `/bili_pending`

查看待审核草稿。

```text
/bili_pending
```

返回内容：

- `draft_id`
- 目标 `rpid`
- 草稿内容摘要

建议在批量监听生成草稿后使用，用来挑选需要发送、编辑或拒绝的草稿。

### `/bili_edit <draft_id> <新内容>`

修改待审核草稿内容。

```text
/bili_edit draft_abcd1234efgh 谢谢提醒，我后续会优化这一点。
```

参数：

- `<draft_id>`：草稿 ID。
- `<新内容>`：新的回复文本。

说明：

- 修改后的内容会重新经过安全检查。
- 安全检查不通过时不会保存。
- 适合在发送前微调语气、补充信息或删除不合适表达。

### `/bili_reject <draft_id>`

拒绝某条草稿。

```text
/bili_reject draft_abcd1234efgh
```

说明：

- 草稿状态会变为 `rejected`。
- 被拒绝的草稿不会再被 `/bili_send` 发送。
- 适合处理不需要回复或生成质量不好的草稿。

### `/bili_send <draft_id>`

发送草稿，或在需要确认时生成确认码。

```text
/bili_send draft_abcd1234efgh
```

执行结果取决于配置：

- `dry_run=true`：不真实发送，只写入演练日志并显示将发送内容。
- `dry_run=false` 且 `require_confirmation=true`：生成 5 分钟有效的确认码。
- `dry_run=false` 且 `require_confirmation=false`：安全检查通过后直接真实发送。

发送前安全检查包括：

- 空内容
- 长度过长
- 敏感词
- 广告倾向
- 攻击性表达
- 重复回复同一评论
- 对同一用户短时间重复回复
- 小时和每日频率限制

注意：

- 真实发送需要 Cookie 中包含 `bili_jct`。
- 建议正式使用保留 `require_confirmation=true`。

### `/bili_confirm <确认码>`

确认真实发送或确认删除操作。

```text
/bili_confirm a1b2c3
```

参数：

- `<确认码>`：由 `/bili_send` 或 `/bili_delete` 生成。

说明：

- 确认码有效期为 5 分钟。
- 确认码只能由发起操作的人使用。
- 过期后需要重新执行 `/bili_send` 或 `/bili_delete`。

### `/bili_dryrun on/off`

切换演练模式。

```text
/bili_dryrun on
/bili_dryrun off
```

说明：

- `on`：不会真实发布、点赞或删除。
- `off`：允许真实操作，但仍受 `require_confirmation` 和安全检查限制。

建议：

- 首次部署先保持 `on`。
- 确认 Cookie、草稿、安全策略都正常后，再切换为 `off`。

### `/bili_monitor_add <BV号> [notify_only|draft|auto_reply] [间隔秒]`

添加评论监听任务。

```text
/bili_monitor_add BV1xxxxxxx
/bili_monitor_add BV1xxxxxxx notify_only 300
/bili_monitor_add BV1xxxxxxx draft 300
/bili_monitor_add BV1xxxxxxx auto_reply 600
```

参数：

- `<BV号>`：要监听的视频 BV 号。
- `[模式]`：可选，默认 `draft`。
- `[间隔秒]`：可选，默认读取 `default_check_interval_seconds`，最低 60 秒。

模式说明：

- `notify_only`：只通知新评论，不生成草稿。
- `draft`：为新评论生成回复草稿，等待人工审核。
- `auto_reply`：满足所有安全条件时自动回复，否则退回草稿。

首次扫描行为：

- 首次扫描只记录现有评论，不处理历史评论。
- 后续扫描才会处理新增评论。
- 这样可以避免刚启用时对旧评论批量生成草稿或回复。

`auto_reply` 额外条件：

- 配置 `auto_reply_enabled=true`
- 配置 `require_confirmation=false`
- 当前不是 `dry_run`
- 回复安全检查通过
- 源评论没有黑名单等风险标记
- 未触发频率限制

### `/bili_monitor_list`

列出监听任务。

```text
/bili_monitor_list
```

返回内容：

- 任务 ID
- 启用或暂停状态
- 模式
- 检查间隔
- BV 号
- 视频标题摘要
- 上次检查时间

### `/bili_monitor_pause <task_id>`

暂停监听任务。

```text
/bili_monitor_pause mon_xxxxxx
```

说明：

- 暂停后任务不会继续检查新评论。
- 任务记录不会删除，可用 `/bili_monitor_resume` 恢复。

### `/bili_monitor_resume <task_id>`

恢复监听任务。

```text
/bili_monitor_resume mon_xxxxxx
```

说明：

- 恢复后调度器会重新开始检查到期任务。
- 如果任务间隔未到，不一定立即执行。

### `/bili_monitor_remove <task_id>`

删除监听任务。

```text
/bili_monitor_remove mon_xxxxxx
```

说明：

- 删除后任务不可恢复。
- 不会删除已经生成的草稿或日志。

### `/bili_monitor_run`

手动触发一次监听检查。

```text
/bili_monitor_run
```

说明：

- 只处理已经到期的监听任务。
- 适合测试监听任务是否正常工作。
- 不会绕过首次扫描保护和安全检查。

### `/bili_blacklist_add <mid> [原因]`

将 B站用户加入黑名单。

```text
/bili_blacklist_add 123456 广告账号
```

参数：

- `<mid>`：B站用户 mid。
- `[原因]`：可选，记录原因。

效果：

- 黑名单用户的新评论不会进入自动回复流程。
- 可以生成待审核草稿，供人工判断。

### `/bili_blacklist_remove <mid>`

移出黑名单。

```text
/bili_blacklist_remove 123456
```

说明：

- 只影响后续安全检查。
- 已经生成的草稿状态不会自动改变。

### `/bili_blacklist_list`

查看黑名单。

```text
/bili_blacklist_list
```

返回内容：

- mid
- 加入时间
- 原因

### `/bili_like <oid> <rpid> [1|0]`

点赞或取消点赞评论。

```text
/bili_like 123456 987654
/bili_like 123456 987654 1
/bili_like 123456 987654 0
```

参数：

- `<oid>`：评论区 oid。视频评论区通常是视频 aid。
- `<rpid>`：评论 ID。
- `[1|0]`：可选，`1` 点赞，`0` 取消点赞，默认 `1`。

注意：

- `dry_run=true` 时不会真实操作。
- 真实操作需要有效 Cookie。

### `/bili_delete <oid> <rpid>`

删除当前登录账号自己发布的评论。

```text
/bili_delete 123456 987654
```

参数：

- `<oid>`：评论区 oid。视频评论区通常是视频 aid。
- `<rpid>`：要删除的评论 ID。

说明：

- 只能删除当前登录账号有权限删除的评论。
- `dry_run=true` 时不会真实删除。
- `require_confirmation=true` 时会生成确认码，需要 `/bili_confirm <确认码>`。

建议保持 `require_confirmation=true`，避免误删。

### `/bili_logs [数量]`

查看最近发布或演练日志。

```text
/bili_logs
/bili_logs 20
```

参数：

- `[数量]`：可选，最多显示 20 条。

返回内容：

- 创建时间
- 成功或失败
- 目标 rpid
- 回复内容摘要

### `/bili_logs_export [数量]`

导出最近日志为 CSV。

```text
/bili_logs_export
/bili_logs_export 500
```

参数：

- `[数量]`：可选，最大 1000。

导出位置：

```text
data/plugin_data/astrbot_plugin_bilibili_assistant/exports/
```

CSV 字段：

- `created_at`
- `success`
- `draft_id`
- `oid`
- `target_rpid`
- `reply_text`
- `error_message`

### `/bili_dynamic_draft <动态内容>`

对动态内容进行安全检查。

```text
/bili_dynamic_draft 今天的视频已经更新，欢迎来看看
```

说明：

- 当前版本只做安全检查，不连接真实动态发布接口。
- 适合未来扩展动态发布前复用安全策略。

### `/bilihelp` / `/bili_help`

显示聊天内完整命令教程。

```text
/bilihelp
/bili_help
```

说明：

- `/bilihelp` 是推荐入口，`/bili_help` 作为兼容别名保留。
- 会按功能分组输出所有命令的用法、参数、示例、推荐流程和安全提示。
- 完整说明以 README 为准。

## 典型使用流程

### 人工审核回复流程

```text
/bili_status
/bili_comments BV1xxxxxxx 5
/bili_draft BV1xxxxxxx 123456 friendly
/bili_pending
/bili_edit draft_abcd1234efgh 谢谢建议，我后续优化。
/bili_send draft_abcd1234efgh
/bili_confirm a1b2c3
```

这个流程适合正式运营。所有回复都经过人工确认，风险最低。

### 只监听新评论

```text
/bili_monitor_add BV1xxxxxxx notify_only 300
/bili_monitor_list
/bili_monitor_run
```

适合只想收到新评论提醒，不希望自动生成草稿。

### 自动生成草稿

```text
/bili_monitor_add BV1xxxxxxx draft 300
/bili_monitor_list
/bili_pending
/bili_send draft_abcd1234efgh
```

适合半自动运营。插件负责发现评论和生成草稿，人负责审核和发送。

### 谨慎开启自动回复

```text
/bili_dryrun on
/bili_monitor_add BV1xxxxxxx auto_reply 600
/bili_monitor_run
```

确认效果后，在 WebUI 中设置：

```text
auto_reply_enabled=true
require_confirmation=false
dry_run=false
```

注意：全自动回复存在误判、上下文不足、平台风控等风险。建议只用于低风险、明确规则的视频评论区。

## 安全设计

- 默认不自动真实发布评论
- 默认 `dry_run=true`
- 默认 `auto_reply_enabled=false`
- 默认 `require_confirmation=true`
- 自动监听首次扫描不处理历史评论
- 真实发布前进行安全检查
- 删除评论默认走确认码
- Cookie 不会在普通聊天输出中完整展示
- Dashboard 扫码成功后不向前端返回完整 Cookie
- 所有发布尝试都会写入 SQLite 日志
- B站请求失败不会无限重试，最多重试 2 次并使用退避
- 持久化数据保存在 AstrBot 数据目录，而不是插件目录

## 数据存储

数据库位置：

```text
data/plugin_data/astrbot_plugin_bilibili_assistant/bilibili_assistant.sqlite3
```

导出日志位置：

```text
data/plugin_data/astrbot_plugin_bilibili_assistant/exports/
```

主要表：

- `monitor_tasks`：监听任务
- `seen_comments`：已见评论
- `reply_drafts`：回复草稿
- `reply_logs`：发布和演练日志
- `blacklisted_users`：黑名单
- `user_reply_cooldowns`：用户回复冷却

## 常见问题

### 为什么能读取评论但不能发送？

通常是以下原因：

- `dry_run=true`
- `require_confirmation=true` 但没有执行 `/bili_confirm`
- Cookie 中缺少 `bili_jct`
- Cookie 失效
- 评论区关闭
- B站风控
- 安全检查未通过

### 为什么提示 csrf 缺失？

B站发布评论需要 `bili_jct` 作为 csrf。请重新扫码登录，或手动填写包含 `bili_jct` 的完整 Cookie。

### 为什么 Dashboard 扫码失败？

可能原因：

- 二维码过期
- B站网页登录接口变动
- 账号触发风控
- AstrBot 所在机器无法访问 B站接口
- 依赖 `qrcode` 未安装

可以执行：

```bash
pip install -r requirements.txt
```

然后重载插件。

### 为什么监听任务没有马上处理评论？

首次扫描只记录现有评论，不处理历史评论。后续新增评论才会触发通知、草稿或自动回复。

### 为什么 `/bili_comments` 提示评论区参数错误？

B站评论接口参数会变化。插件会优先使用当前主评论接口，并在参数错误时自动回退到旧评论接口。若仍失败，通常是视频评论区关闭、接口风控、网络不可达或 B站接口临时调整。

### 为什么不建议直接全自动？

评论区运营需要上下文判断。全自动容易误伤用户、回复不合时宜、触发平台风控，也不利于账号长期安全。

### 如何查看某条评论的 `rpid`？

先执行：

```text
/bili_comments BV1xxxxxxx 5
```

返回列表中会包含 `rpid`。

### 怎么区分评论和评论的评论？

`/bili_comments` 会在每条前面显示层级：

```text
1. 【主评论】用户名(mid=...) | rpid=... | 回复数=...
  ↳ 2. 【评论回复】用户名(mid=...) | rpid=... | root=... | parent=...
```

`主评论` 表示视频下的一级评论。`评论回复` 表示某条评论下面的楼中楼回复。对楼中楼回复使用 `/bili_draft <BV号> <rpid>` 时，插件会自动使用正确的 `root` 和 `parent` 参数。

### `oid` 是什么？

视频评论区的 `oid` 通常是视频 `aid`。可以通过：

```text
/bili_video BV1xxxxxxx
```

查看视频 `aid`。

## 开发者说明

模块结构：

```text
main.py
metadata.yaml
_conf_schema.json
requirements.txt
pages/
  dashboard/
    index.html
    app.js
    style.css
.astrbot-plugin/
  i18n/
    zh-CN.json
bilicomment_core/
  bilibili_client.py
  models.py
  storage.py
  scheduler.py
  rules.py
  reply_generator.py
  safety.py
  utils.py
tests/
  test_bilibili_client.py
  test_models.py
  test_plugin_loading.py
  test_rules.py
  test_safety.py
  test_storage.py
```

扩展建议：

- 扩展动态发布时，新增 `bilicomment_core/dynamic_client.py` 和独立草稿模型。
- 增加新的评论区类型时，扩展 `BilibiliClient`，不要在命令中硬编码 URL。
- Dashboard 复杂功能应通过 `pages/` 和 `context.register_web_api()` 增加，不建议把复杂交互都塞进聊天命令。
- 所有真实发布能力都应继续复用 `SafetyChecker`、日志和人工确认流程。
