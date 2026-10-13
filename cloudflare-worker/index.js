/**
 * DSA Discord Bridge — Cloudflare Worker
 *
 * 两个职责：
 * 1) Cron Trigger（工作日 UTC 10:00 = 北京时间/香港时间 18:00）通过 GitHub
 *    workflow_dispatch 精确触发「每日股票分析」，替代 GitHub 自身可能延迟数小时的
 *    schedule 触发。
 * 2) Discord Interactions 端点：提供 /analyze 斜杠命令，带 Yes/No 按钮确认后，
 *    以 stocks 输入触发工作流（stocks-only 模式）。
 *
 * 需要的 Worker 环境变量：
 *   变量: GITHUB_REPO (owner/repo), GITHUB_WORKFLOW (可选, 默认 00-daily-analysis.yml)
 *   密钥: GITHUB_PAT (classic, workflow 权限), DISCORD_PUBLIC_KEY (Discord 应用公钥)
 *   可选密钥: DISCORD_WEBHOOK_URL (cron 触发失败时告警)
 */

const API = "https://api.github.com";
const DISCORD_API = "https://discord.com/api/v10";

function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  return bytes;
}

async function verifyDiscordSignature(request, rawBody, publicKeyHex) {
  const signature = request.headers.get("X-Signature-Ed25519");
  const timestamp = request.headers.get("X-Signature-Timestamp");
  if (!signature || !timestamp || !publicKeyHex) return false;
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      hexToBytes(publicKeyHex),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const payload = new TextEncoder().encode(timestamp + rawBody);
    return await crypto.subtle.verify(
      { name: "Ed25519" },
      key,
      hexToBytes(signature),
      payload,
    );
  } catch (err) {
    console.error("signature verify failed", err);
    return false;
  }
}

async function dispatchWorkflow(env, inputs) {
  const repo = env.GITHUB_REPO;
  const workflow = env.GITHUB_WORKFLOW || "00-daily-analysis.yml";
  const resp = await fetch(
    `${API}/repos/${repo}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_PAT}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "dsa-discord-bridge",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    },
  );
  if (resp.status !== 204) {
    const text = await resp.text();
    throw new Error(`dispatch failed: ${resp.status} ${text}`);
  }
}

async function alertDiscord(env, content) {
  if (!env.DISCORD_WEBHOOK_URL) return;
  try {
    await fetch(env.DISCORD_WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "My Frd", content }),
    });
  } catch (err) {
    console.error("alert post failed", err);
  }
}

function interactionResponse(data) {
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
}

function ephemeral(content) {
  return interactionResponse({ type: 4, data: { content, flags: 64 } });
}

function updateMessage(content, components = []) {
  return interactionResponse({
    type: 7,
    data: { content, components },
  });
}

async function handleInteraction(request, env) {
  const rawBody = await request.text();
  const valid = await verifyDiscordSignature(request, rawBody, env.DISCORD_PUBLIC_KEY);
  if (!valid) {
    return new Response("invalid request signature", { status: 401 });
  }

  const interaction = JSON.parse(rawBody);
  const type = interaction.type;

  // PING
  if (type === 1) {
    return interactionResponse({ type: 1 });
  }

  // 斜杠命令
  if (type === 2 && interaction.data?.name === "analyze") {
    const options = interaction.data.options || [];
    const symbolOption = options.find((opt) => opt.name === "symbol");
    const symbol = (symbolOption?.value || "").trim().toUpperCase();
    if (!symbol) {
      return ephemeral("请提供股票代码，例如 `/analyze NVDA`。");
    }
    return interactionResponse({
      type: 4,
      data: {
        content: `要生成 **${symbol}** 的分析报告吗？`,
        flags: 64,
        components: [
          {
            type: 1,
            components: [
              { type: 2, style: 3, label: "Yes", custom_id: `analyze_yes:${symbol}` },
              { type: 2, style: 4, label: "No", custom_id: "analyze_no" },
            ],
          },
        ],
      },
    });
  }

  // 按钮组件
  if (type === 3) {
    const customId = interaction.data?.custom_id || "";
    if (customId.startsWith("analyze_yes:")) {
      const symbol = customId.split(":", 2)[1] || "";
      try {
        await dispatchWorkflow(env, { mode: "stocks-only", stocks: symbol });
        return updateMessage(
          `🚀 已开始生成 **${symbol}** 的分析报告，完成后会推送到当日频道。`,
        );
      } catch (err) {
        console.error(err);
        return updateMessage(`⚠️ 触发失败：${String(err.message || err)}`);
      }
    }
    if (customId === "analyze_no") {
      return updateMessage("已取消。");
    }
  }

  return ephemeral("暂不支持该交互。");
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("dsa-discord-bridge", { status: 200 });
    }
    try {
      return await handleInteraction(request, env);
    } catch (err) {
      console.error("interaction handling failed", err);
      return new Response("internal error", { status: 500 });
    }
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      dispatchWorkflow(env, { mode: "full" }).catch(async (err) => {
        console.error("cron dispatch failed", err);
        await alertDiscord(env, `⚠️ 定时触发失败：${String(err.message || err)}`);
      }),
    );
  },
};
