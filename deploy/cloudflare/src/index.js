import { Container, getContainer } from "@cloudflare/containers";
import { DurableObject, env } from "cloudflare:workers";

const value = (name, fallback = "") => String(env[name] ?? fallback);
const SESSION_COOKIE = "proofforge_judge";
const MAX_REQUEST_BYTES = 32_768;

const json = (payload, init = {}) => new Response(JSON.stringify(payload), {
  ...init,
  headers: { "content-type": "application/json; charset=utf-8", ...(init.headers || {}) }
});

const sha256 = async (value) => {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
};

const randomToken = () => {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
};

const constantTimeEqual = (left, right) => {
  const a = new TextEncoder().encode(String(left));
  const b = new TextEncoder().encode(String(right));
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let index = 0; index < a.length; index += 1) mismatch |= a[index] ^ b[index];
  return mismatch === 0;
};

export class JudgeLedger extends DurableObject {
  async readState() {
    return (await this.ctx.storage.get("state")) || {
      sessions: {},
      reservations: {},
      failures: {},
      totalRuns: 0,
      activeSession: null
    };
  }

  async writeState(state) {
    await this.ctx.storage.put("state", state);
  }

  async fetch(request) {
    const url = new URL(request.url);
    const now = Math.floor(Date.now() / 1000);
    const state = await this.readState();
    for (const [hash, session] of Object.entries(state.sessions)) {
      if (session.expiresAt <= now) delete state.sessions[hash];
    }
    for (const [key, reservation] of Object.entries(state.reservations)) {
      if (reservation.expiresAt <= now) {
        if (state.activeSession === reservation.sessionHash) state.activeSession = null;
        delete state.reservations[key];
      }
    }
    if (url.pathname === "/login") {
      const body = await request.json().catch(() => ({}));
      const ip = String(body.ip || "unknown").slice(0, 80);
      const failure = state.failures[ip] || { count: 0, windowStart: now };
      if (failure.windowStart + 900 <= now) { failure.count = 0; failure.windowStart = now; }
      if (failure.count >= 5) {
        await this.writeState(state);
        return json({ ok: false, reason: "rate_limited" }, { status: 429 });
      }
      if (!body.ok) {
        failure.count += 1;
        state.failures[ip] = failure;
        await this.writeState(state);
        return json({ ok: false, reason: "invalid" }, { status: 401 });
      }
      // Recover reservations left behind by a container crash or rollout. A
      // live session that has not touched the ledger for five minutes cannot
      // still be an active browser run; this prevents a failed provider call
      // from consuming the lane until the full session TTL elapses.
      if (state.activeSession) {
        const active = state.sessions[state.activeSession];
        if (!active || !active.lastSeen || now - active.lastSeen > 300) {
          for (const [key, reservation] of Object.entries(state.reservations)) {
            if (reservation.sessionHash === state.activeSession) delete state.reservations[key];
          }
          if (active) active.activeRunId = null;
          state.activeSession = null;
        }
      }
      const token = String(body.token || "");
      if (token.length < 64) return json({ ok: false, reason: "invalid" }, { status: 401 });
      const sessionHash = await sha256(token);
      state.sessions[sessionHash] = {
        sessionHash,
        expiresAt: now + Math.min(1800, Math.max(300, Number(body.ttlSeconds) || 900)),
        runsUsed: 0,
        maxRuns: Math.min(3, Math.max(1, Number(body.maxRuns) || 3)),
        activeRunId: null,
        lastSeen: now
      };
      delete state.failures[ip];
      await this.writeState(state);
      return json({ ok: true, expiresAt: state.sessions[sessionHash].expiresAt });
    }
    if (url.pathname === "/authorize") {
      const body = await request.json().catch(() => ({}));
      const sessionHash = await sha256(String(body.token || ""));
      const session = state.sessions[sessionHash];
      const idem = String(body.idempotency || "").slice(0, 128);
      if (!session || session.expiresAt <= now || !idem) {
        await this.writeState(state);
        return json({ ok: false, reason: "unauthorized" }, { status: 401 });
      }
      const existing = state.reservations[idem];
      if (existing && existing.sessionHash === sessionHash) {
        await this.writeState(state);
        return json({ ok: true, reservation: existing, replay: true });
      }
      if (session.activeRunId || (state.activeSession && state.activeSession !== sessionHash)) {
        await this.writeState(state);
        return json({ ok: false, reason: "active_run" }, { status: 409 });
      }
      if (session.runsUsed >= session.maxRuns || state.totalRuns >= 6) {
        await this.writeState(state);
        return json({ ok: false, reason: "quota" }, { status: 429 });
      }
      const reservation = {
        sessionHash,
        idempotency: idem,
        runId: null,
        expiresAt: now + 900
      };
      state.reservations[idem] = reservation;
      state.activeSession = sessionHash;
      session.lastSeen = now;
      session.runsUsed += 1;
      session.activeRunId = `pending:${idem}`;
      state.totalRuns += 1;
      await this.writeState(state);
      return json({ ok: true, reservation });
    }
    if (url.pathname === "/bind") {
      const body = await request.json().catch(() => ({}));
      const reservation = state.reservations[String(body.idempotency || "")];
      if (!reservation || reservation.sessionHash !== await sha256(String(body.token || ""))) {
        return json({ ok: false }, { status: 401 });
      }
      reservation.runId = String(body.runId || "").slice(0, 80) || null;
      const session = state.sessions[reservation.sessionHash];
      if (session) session.activeRunId = reservation.runId || session.activeRunId;
      await this.writeState(state);
      return json({ ok: true });
    }
    if (url.pathname === "/release") {
      const body = await request.json().catch(() => ({}));
      const tokenHash = await sha256(String(body.token || ""));
      const session = state.sessions[tokenHash];
      if (session) session.lastSeen = now;
      if (!session) return json({ ok: false }, { status: 401 });
      for (const [key, reservation] of Object.entries(state.reservations)) {
        if (reservation.sessionHash === tokenHash && (!body.runId || reservation.runId === body.runId)) {
          delete state.reservations[key];
        }
      }
      session.activeRunId = null;
      if (state.activeSession === tokenHash) state.activeSession = null;
      await this.writeState(state);
      return json({ ok: true });
    }
    if (url.pathname === "/validate") {
      const tokenHash = await sha256(String(url.searchParams.get("token") || ""));
      const session = state.sessions[tokenHash];
      await this.writeState(state);
      return json({ ok: Boolean(session && session.expiresAt > now), session });
    }
    return json({ ok: false }, { status: 404 });
  }
}

export class ProofForgeContainer extends Container {
  defaultPort = 8000;
  requiredPorts = [8000];
  pingEndpoint = "localhost/api/health";
  sleepAfter = "30m";
  enableInternet = true;
  envVars = {
    PROOFFORGE_DATA_DIR: "/app/data",
    PROOFFORGE_ENABLE_LIVE: value("PROOFFORGE_ENABLE_LIVE", "false"),
    PROOFFORGE_ENABLE_JUDGE_SANDBOX: value("PROOFFORGE_ENABLE_JUDGE_SANDBOX", "false"),
    PROOFFORGE_OPERATOR_TOKEN: value("PROOFFORGE_OPERATOR_TOKEN"),
    PROOFFORGE_SIGNING_KEY: value("PROOFFORGE_SIGNING_KEY"),
    PROOFFORGE_JUDGE_CAPABILITY_KEY: value("PROOFFORGE_JUDGE_CAPABILITY_KEY"),
    PROOFFORGE_JUDGE_USERNAME: value("PROOFFORGE_JUDGE_USERNAME"),
    PROOFFORGE_JUDGE_PASSWORD: value("PROOFFORGE_JUDGE_PASSWORD"),
    PROOFFORGE_JUDGE_TTL_SECONDS: value("PROOFFORGE_JUDGE_TTL_SECONDS", "1800"),
    PROOFFORGE_JUDGE_MAX_RUNS: value("PROOFFORGE_JUDGE_MAX_RUNS", "3"),
    PROOFFORGE_TRUST_EDGE_CLIENT_IP: "true",
    OPENAI_API_KEY: value("OPENAI_API_KEY"),
    B2_KEY_ID: value("B2_KEY_ID"),
    B2_APP_KEY: value("B2_APP_KEY"),
    B2_BUCKET: value("B2_BUCKET"),
    B2_REGION: value("B2_REGION"),
    B2_PUBLIC_URL_BASE: value("B2_PUBLIC_URL_BASE")
  };
}

export default {
  async fetch(request, workerEnv) {
    const url = new URL(request.url);
    const clientIp = request.headers.get("CF-Connecting-IP") || "unknown";
    const ledger = workerEnv.PROOFFORGE_JUDGE_LEDGER
      ? workerEnv.PROOFFORGE_JUDGE_LEDGER.get(workerEnv.PROOFFORGE_JUDGE_LEDGER.idFromName("global"))
      : null;
    const cookieToken = request.headers.get("Cookie")?.match(new RegExp(`${SESSION_COOKIE}=([^;]+)`))?.[1] || "";
    const suppliedToken = cookieToken || request.headers.get("X-Proofforge-Judge-Session") || "";

    if (url.pathname === "/api/judge/login" && request.method === "POST") {
      if (!ledger) return json({ detail: "judge ledger is not configured" }, { status: 503 });
      const body = await request.clone().json().catch(() => ({}));
      const suppliedUser = String(body.username || "");
      const suppliedPassword = String(body.password || "");
      const valid = constantTimeEqual(suppliedUser, value("PROOFFORGE_JUDGE_USERNAME"))
        && constantTimeEqual(suppliedPassword, value("PROOFFORGE_JUDGE_PASSWORD"));
      const token = valid ? randomToken() : "";
      const result = await ledger.fetch(new Request("https://ledger/login", {
        method: "POST",
        body: JSON.stringify({
          ok: valid,
          token,
          ip: clientIp,
          ttlSeconds: Number(value("PROOFFORGE_JUDGE_TTL_SECONDS", "900")),
          maxRuns: Number(value("PROOFFORGE_JUDGE_MAX_RUNS", "3"))
        }),
        headers: { "content-type": "application/json" }
      }));
      if (!result.ok) return json({ detail: result.status === 429 ? "login temporarily rate-limited" : "invalid judge credentials" }, { status: result.status });
      const payload = await result.json();
      const response = json({ ok: true, expiresAt: payload.expiresAt, maxRuns: Number(value("PROOFFORGE_JUDGE_MAX_RUNS", "3")) });
      response.headers.append("Set-Cookie", `${SESSION_COOKIE}=${token}; Max-Age=900; Path=/; HttpOnly; Secure; SameSite=Strict`);
      return response;
    }
    if (url.pathname === "/api/judge/logout" && request.method === "POST") {
      if (ledger && suppliedToken) await ledger.fetch(new Request("https://ledger/release", { method: "POST", body: JSON.stringify({ token: suppliedToken }), headers: { "content-type": "application/json" } }));
      const response = json({ ok: true });
      response.headers.append("Set-Cookie", `${SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Strict`);
      return response;
    }

    let liveRequest = false;
    if (request.method === "POST" && url.pathname === "/api/runs") {
      const body = await request.clone().json().catch(() => ({}));
      liveRequest = body.mode === "live";
      if (liveRequest) {
        if (!ledger || !suppliedToken) return json({ detail: "judge login required for live generation" }, { status: 401 });
        const idem = request.headers.get("X-Proofforge-Idempotency-Key") || `live-${await sha256(JSON.stringify(body))}`;
        const authorization = await ledger.fetch(new Request("https://ledger/authorize", { method: "POST", body: JSON.stringify({ token: suppliedToken, idempotency: idem }), headers: { "content-type": "application/json" } }));
        if (!authorization.ok) {
          const reason = (await authorization.json().catch(() => ({}))).reason;
          const status = reason === "quota" ? 429 : reason === "active_run" ? 409 : 401;
          return json({ detail: reason === "quota" ? "judge live-run quota exhausted" : reason === "active_run" ? "one live run is already active" : "judge login required for live generation" }, { status });
        }
      }
    } else if (suppliedToken && url.pathname.startsWith("/api/runs")) {
      liveRequest = true;
    }

    // Version the named instance when the container image changes. The previous
    // instance can remain warm; a new name makes the release read back the image
    // whose digest was just deployed instead of silently serving stale code.
    const container = getContainer(
      workerEnv.PROOFFORGE_CONTAINER,
      "public-single-replica-security-20260718"
    );
    const headers = new Headers(request.headers);
    headers.delete("X-Proofforge-Client-IP");
    if (clientIp) headers.set("X-Proofforge-Client-IP", clientIp);
    if (liveRequest && suppliedToken) {
      const operator = value("PROOFFORGE_OPERATOR_TOKEN");
      if (operator) headers.set("X-Proofforge-Key", operator);
      headers.delete("X-Proofforge-Judge-Session");
    }
    const response = await container.fetch(new Request(request, { headers }));
    if (liveRequest && suppliedToken && request.method === "POST" && url.pathname === "/api/runs" && ledger) {
      const payload = await response.clone().json().catch(() => ({}));
      const runId = payload?.run?.id;
      const idem = request.headers.get("X-Proofforge-Idempotency-Key") || `live-${await sha256(JSON.stringify(await request.clone().json().catch(() => ({}))))}`;
      if (runId) await ledger.fetch(new Request("https://ledger/bind", { method: "POST", body: JSON.stringify({ token: suppliedToken, idempotency: idem, runId }), headers: { "content-type": "application/json" } }));
    }
    if (liveRequest && suppliedToken && ledger && request.method === "GET" && url.pathname.match(/^\/api\/runs\/[^/]+$/)) {
      const payload = await response.clone().json().catch(() => ({}));
      if (["completed", "failed"].includes(payload?.status)) await ledger.fetch(new Request("https://ledger/release", { method: "POST", body: JSON.stringify({ token: suppliedToken, runId: payload.id }), headers: { "content-type": "application/json" } }));
    }
    return response;
  }
};
