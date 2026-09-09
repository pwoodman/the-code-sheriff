/**
 * Optional webhook for The Code Sheriff.
 * Keep event selection in sync with quality_gates.github_app.job_from_webhook.
 */

const CHECK_NAME = "The Code Sheriff";
const DISPATCH_EVENT = "the-codesheriff";
const USER_AGENT = "the-codesheriff";
const PULL_ACTIONS = new Set([
  "opened",
  "synchronize",
  "reopened",
  "ready_for_review",
]);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return json({ ok: true, app: "the-codesheriff" });
    }
    if (request.method !== "POST" || !["/", "/webhook", "/event"].includes(url.pathname)) {
      return json({ error: "not found" }, 404);
    }
    const secret = env.WEBHOOK_SECRET || env.QUALITY_APP_WEBHOOK_SECRET || "";
    const body = await request.arrayBuffer();
    const signature = request.headers.get("x-hub-signature-256");
    if (!(await verifySignature(secret, signature, body))) {
      return json({ error: "invalid signature" }, 401);
    }
    let payload;
    try {
      payload = JSON.parse(new TextDecoder().decode(body) || "{}");
    } catch {
      return json({ error: "invalid json" }, 400);
    }
    const event = request.headers.get("x-github-event") || "";
    const job = jobFromWebhook(event, payload);
    if (!job) {
      return json({ ok: true, ignored: event || "unknown" }, 202);
    }
    if (job.kind === "ping") {
      return json({ ok: true, pong: true });
    }
    if (job.kind === "installed") {
      return json({ ok: true, installed: job.account || "" });
    }
    const home = env.HOME_REPO || "pwoodman/the-code-sheriff";
    const handleHome = ["1", "true", "yes"].includes(
      String(env.QUALITY_APP_HANDLE_HOME || "").toLowerCase(),
    );
    if (!handleHome && job.repository === home) {
      return json({ ok: true, skipped: "home repository runs sheriff.yml" }, 202);
    }
    const token = env.DISPATCH_TOKEN || env.QUALITY_APP_DISPATCH_TOKEN || "";
    if (!token) {
      return json({ error: "DISPATCH_TOKEN is not set" }, 503);
    }
    const unsigned = {
      repository: job.repository,
      sha: job.sha,
      pr: job.pr,
      installation_id: job.installation_id,
      base: job.base,
      fork: job.fork,
    };
    unsigned.sig = await signDispatch(secret, unsigned);
    const response = await fetch(`https://api.github.com/repos/${home}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
      },
      body: JSON.stringify({ event_type: DISPATCH_EVENT, client_payload: unsigned }),
    });
    if (!response.ok) {
      const text = await response.text();
      return json({ error: "dispatch failed", github: text.slice(0, 300) }, 502);
    }
    return json({ ok: true, dispatched: unsigned.repository, pr: unsigned.pr }, 202);
  },
};

function jobFromWebhook(event, payload) {
  if (event === "ping") {
    return { kind: "ping" };
  }
  if (event === "installation" && payload.action === "created") {
    return { kind: "installed", account: payload.installation?.account?.login || "" };
  }
  if (event === "pull_request") {
    const pull = payload.pull_request || {};
    if (!PULL_ACTIONS.has(payload.action)) {
      return null;
    }
    if (pull.draft && payload.action !== "ready_for_review") {
      return null;
    }
    return runJob({
      repository: payload.repository?.full_name,
      sha: pull.head?.sha,
      pr: pull.number,
      installation_id: payload.installation?.id,
      base: pull.base?.ref,
      fork: isFork(pull, payload.repository?.full_name),
    });
  }
  if (event === "check_run" && payload.action === "rerequested") {
    const check = payload.check_run || {};
    if (check.name !== CHECK_NAME && check.name !== "quality-review") {
      return null;
    }
    const pull = (check.pull_requests || [])[0] || {};
    return runJob({
      repository: payload.repository?.full_name,
      sha: check.head_sha,
      pr: pull.number,
      installation_id: payload.installation?.id,
      base: pull.base?.ref,
      fork: "false",
    });
  }
  return null;
}

function isFork(pull, repository) {
  const headRepo = pull.head?.repo?.full_name;
  return headRepo && headRepo !== repository ? "true" : "false";
}

function runJob({ repository, sha, pr, installation_id, base, fork }) {
  if (!repository || !sha || !pr || !installation_id) {
    return null;
  }
  return {
    kind: "run",
    repository: String(repository),
    sha: String(sha),
    pr: String(pr),
    installation_id: String(installation_id),
    base: String(base || "main"),
    fork,
  };
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function verifySignature(secret, header, body) {
  if (!secret || !header) {
    return false;
  }
  const hex = header.split("=")[1];
  if (!hex) {
    return false;
  }
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify("HMAC", key, hexToBytes(hex), body);
}

async function signDispatch(secret, payload) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const canonical = canonicalJson(payload);
  const sig = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(canonical),
  );
  return bytesToHex(new Uint8Array(sig));
}

function canonicalJson(payload) {
  return JSON.stringify(payload, Object.keys(payload).sort());
}

function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i += 1) {
    bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

function bytesToHex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
