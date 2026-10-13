# DSA Discord Bridge (Cloudflare Worker)

精确的每日触发 + Discord `/analyze` 命令桥。部署一次，免费额度足够（每天 1 次 cron + 少量交互）。

## 它做什么

1. **精确调度**：每个工作日 UTC 10:00（香港/北京时间 18:00）调用 GitHub `workflow_dispatch`，避免 GitHub 自带 cron 的数小时延迟。
2. **Discord 命令**：`/analyze NVDA` → 弹出 Yes/No 按钮 → 点 Yes 后以 `stocks=NVDA` 触发工作流（stocks-only 模式），报告按正常通知流程推送。
3. **失败告警**：cron 触发失败时向 `DISCORD_WEBHOOK_URL` 发送提醒。

## 部署步骤

### 1. 准备 GitHub PAT

建议复用 keep-alive 的 PAT（classic，勾选 `workflow` 权限）。没有则新建：
GitHub → Settings → Developer settings → Personal access tokens (classic) → Generate new token → 勾选 `workflow` → 复制。

### 2. 创建 Discord 应用（若尚未创建）

1. https://discord.com/developers/applications → New Application，命名 **My Frd**。
2. General Information 页复制 **Public Key**（稍后填 Worker 密钥）。
3. 安装 wrangler 并登录 Cloudflare（需要 Cloudflare 账号，免费）：

```bash
cd cloudflare-worker
npm install -g wrangler
wrangler login
```

### 3. 配置密钥并部署

```bash
wrangler secret put GITHUB_PAT          # 粘贴第 1 步的 PAT
wrangler secret put DISCORD_PUBLIC_KEY  # 粘贴第 2 步的 Public Key
wrangler secret put DISCORD_WEBHOOK_URL # 可选：cron 失败告警用
wrangler deploy
```

部署成功后会输出 Worker URL，例如 `https://dsa-discord-bridge.<account>.workers.dev`。

### 4. 把 Worker URL 接到 Discord

1. Discord Developer Portal → 你的应用 → General Information → **Interactions Endpoint URL** 填 Worker URL → Save（Discord 会发送 PING 校验，Worker 已实现）。
2. 注册 `/analyze` 命令（一次性，把 `YOUR_APP_ID` 和 `YOUR_BOT_TOKEN` 换成实际值）：

```bash
curl -X PUT "https://discord.com/api/v10/applications/YOUR_APP_ID/commands" \
  -H "Authorization: Bot YOUR_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{"name":"analyze","description":"生成某只股票的分析报告","options":[{"type":3,"name":"symbol","description":"股票代码，如 NVDA","required":true}]}]'
```

3. 在服务器频道输入 `/analyze NVDA` 测试：应弹出 Yes/No；点 Yes 后几秒内 Discord 收到确认，稍后报告出现在当日频道。

### 5. 关闭 GitHub 自带的 schedule（避免重复运行）

Worker 的 cron 验证可用后，在仓库 Settings → Secrets and variables → Actions → Variables 里新增：

| 变量 | 值 |
|---|---|
| `USE_GITHUB_SCHEDULE` | `false` |

工作流会保留 `schedule` 作为兜底，但定时触发将被跳过（手动触发和 Worker 触发不受影响）。

## 本地开发/测试

```bash
wrangler dev
```

- 本地 `http://localhost:8787` 可用于手动调试；Discord 签名校验需要真实 Public Key。
- cron 可用 `wrangler dev --test-scheduled` + `curl "http://localhost:8787/__scheduled?cron=0+10+*+*+1-5"` 触发。

## 回滚

1. 删除或停用 Worker（`wrangler delete`）。
2. 删除仓库变量 `USE_GITHUB_SCHEDULE`（或设为 `true`），GitHub 自带 cron 恢复为唯一触发。
