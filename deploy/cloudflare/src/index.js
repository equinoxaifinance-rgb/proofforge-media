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
    PROOFFORGE_OPERATOR_TOKEN: value("PROOFFORGE_OPERATOR_TOKEN"),
    PROOFFORGE_SIGNING_KEY: value("PROOFFORGE_SIGNING_KEY"),
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
    const container = getContainer(workerEnv.PROOFFORGE_CONTAINER, "public-single-replica");
    const headers = new Headers(request.headers);
    headers.delete("X-Proofforge-Client-IP");
    const clientIp = request.headers.get("CF-Connecting-IP");
    if (clientIp) headers.set("X-Proofforge-Client-IP", clientIp);
    return container.fetch(new Request(request, { headers }));
  }
};
