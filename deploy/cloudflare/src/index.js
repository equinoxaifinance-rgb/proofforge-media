import { Container, getContainer } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

const value = (name, fallback = "") => String(env[name] ?? fallback);

export class ProofForgeContainer extends Container {
  defaultPort = 8000;
  requiredPorts = [8000];
  pingEndpoint = "api/health";
  sleepAfter = "30m";
  enableInternet = true;
  envVars = {
    PROOFFORGE_DATA_DIR: "/app/data",
    PROOFFORGE_ENABLE_LIVE: value("PROOFFORGE_ENABLE_LIVE", "false"),
    PROOFFORGE_OPERATOR_TOKEN: value("PROOFFORGE_OPERATOR_TOKEN"),
    PROOFFORGE_SIGNING_KEY: value("PROOFFORGE_SIGNING_KEY"),
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
    return container.fetch(request);
  }
};
