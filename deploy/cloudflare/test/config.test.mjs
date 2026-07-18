import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const config = JSON.parse(fs.readFileSync(new URL("../wrangler.jsonc", import.meta.url), "utf8"));
const source = fs.readFileSync(new URL("../src/index.js", import.meta.url), "utf8");

test("routes every judge request to one named container", () => {
  assert.equal(config.containers.length, 1);
  assert.equal(config.containers[0].max_instances, 1);
  assert.equal(config.containers[0].instance_type, "lite");
  assert.match(source, /getContainer\(workerEnv\.PROOFFORGE_CONTAINER, "public-single-replica"\)/);
});

test("passes required live credentials only through Worker secrets", () => {
  for (const name of [
    "OPENAI_API_KEY",
    "B2_KEY_ID",
    "B2_APP_KEY",
    "B2_BUCKET",
    "B2_REGION",
    "PROOFFORGE_OPERATOR_TOKEN",
    "PROOFFORGE_SIGNING_KEY"
  ]) {
    assert.match(source, new RegExp(`value\\(\\"${name}\\"`));
    assert.equal(JSON.stringify(config).includes(name), false);
  }
});

test("uses the pinned application Dockerfile and health endpoint", () => {
  assert.equal(config.containers[0].image, "../../Dockerfile");
  assert.match(source, /defaultPort = 8000/);
  assert.match(source, /pingEndpoint = "api\/health"/);
});
