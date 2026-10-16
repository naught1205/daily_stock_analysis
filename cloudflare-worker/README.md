# DSA Discord Bridge (Cloudflare Worker)

精確的每日觸發 + Discord `/analyze` 命令橋。部署一次，免費額度足夠（每天 1 次 cron + 少量互動）。

## 它做什麼

1. **精確調度**：每個工作日 UTC 10:00（香港/北京時間 18:00）呼叫 GitHub `workflow_dispatch`，避免 GitHub 自帶 cron 的數小時延遲。
2. **Discord 命令**：`/analyze NVDA` → 彈出 Yes/No 按鈕 → 點 Yes 後以 `stocks=NVDA` 觸發工作流（stocks-only 模式），報告按正常通知流程推送。
3. **失敗告警**：cron 觸發失敗時向 `DISCORD_WEBHOOK_URL` 發送提醒。

## 部署步驟

### 1. 準備 GitHub PAT

建議復用 keep-alive 的 PAT（classic，勾選 `workflow` 權限）。沒有則新建：
GitHub → Settings → Developer settings → Personal access tokens (classic) → Generate new token → 勾選 `workflow` → 複製。

### 2. 建立 Discord 應用（若尚未建立）

1. https://discord.com/developers/applications → New Application，命名 **My Frd**。
2. General Information 頁複製 **Public Key**（稍後填入 Worker 密鑰）。
3. 安裝 wrangler 並登入 Cloudflare（需要 Cloudflare 帳號，免費）：

```bash
cd cloudflare-worker
npm install -g wrangler
wrangler login
```

### 3. 設定密鑰並部署

```bash
wrangler secret put GITHUB_PAT          # 貼上第 1 步的 PAT
wrangler secret put DISCORD_PUBLIC_KEY  # 貼上第 2 步的 Public Key
wrangler secret put DISCORD_WEBHOOK_URL # 可選：cron 失敗告警用
wrangler deploy
```

部署成功後會輸出 Worker URL，例如 `https://dsa-discord-bridge.<account>.workers.dev`。

### 4. 把 Worker URL 接到 Discord

1. Discord Developer Portal → 你的應用 → General Information → **Interactions Endpoint URL** 填入 Worker URL → Save（Discord 會發送 PING 校驗，Worker 已實現）。
2. 註冊 `/analyze` 命令（一次性，把 `YOUR_APP_ID` 和 `YOUR_BOT_TOKEN` 換成實際值）：

```bash
curl -X PUT "https://discord.com/api/v10/applications/YOUR_APP_ID/commands" \
  -H "Authorization: Bot YOUR_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{"name":"analyze","description":"產生某隻股票的分析報告","options":[{"type":3,"name":"symbol","description":"股票代碼，例如 NVDA","required":true}]}]'
```

> 想立即生效可改用伺服器層級端點 `/applications/YOUR_APP_ID/guilds/YOUR_GUILD_ID/commands`（需要開啟開發者模式的「複製伺服器 ID」）。

3. 在伺服器頻道輸入 `/analyze NVDA` 測試：應彈出 Yes/No；點 Yes 後幾秒內 Discord 收到確認，稍後報告出現在當日頻道。

### 5. 關閉 GitHub 自帶的 schedule（避免重複執行）

Worker 的 cron 驗證可用後，在倉庫 Settings → Secrets and variables → Actions → Variables 裡新增：

| 變數 | 值 |
|---|---|
| `USE_GITHUB_SCHEDULE` | `false` |

工作流會保留 `schedule` 作為兜底，但定時觸發將被跳過（手動觸發和 Worker 觸發不受影響）。

## 本地開發/測試

```bash
wrangler dev
```

- 本地 `http://localhost:8787` 可用於手動除錯；Discord 簽名校驗需要真實 Public Key。
- cron 可用 `wrangler dev --test-scheduled` + `curl "http://localhost:8787/__scheduled?cron=0+10+*+*+1-5"` 觸發。

## 回滾

1. 刪除或停用 Worker（`wrangler delete`）。
2. 刪除倉庫變數 `USE_GITHUB_SCHEDULE`（或設為 `true`），GitHub 自帶 cron 恢復為唯一觸發。
