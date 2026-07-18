import { Container, getContainer } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

const value = (name, fallback = "") => String(env[name] ?? fallback);

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
    // Version the named instance when the container image changes. The previous
    // instance can remain warm; a new name makes the release read back the image
    // whose digest was just deployed instead of silently serving stale code.
    const container = getContainer(
      workerEnv.PROOFFORGE_CONTAINER,
      "public-single-replica-security-20260718"
    );
    const headers = new Headers(request.headers);
    headers.delete("X-Proofforge-Client-IP");
    const clientIp = request.headers.get("CF-Connecting-IP");
    if (clientIp) headers.set("X-Proofforge-Client-IP", clientIp);
    return container.fetch(new Request(request, { headers }));
  }
};
