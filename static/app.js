const form = document.querySelector("#brief-form");
const submit = form.querySelector("button[type=submit]");
const empty = document.querySelector("#empty-state");
const resultPanel = document.querySelector("#run-result");
const errorPanel = document.querySelector("#error-state");
const heading = document.querySelector("#run-heading");
const approveButton = document.querySelector("#approve-button");
const bundleButton = document.querySelector("#bundle-button");
const reviewStatus = document.querySelector("#review-status");
let currentRun = null;
let currentAccessToken = null;
let currentAssetObjectUrl = null;
let isSubmitting = false;
const demoSessionKey = (() => {
  const existing = sessionStorage.getItem("proofforge-demo-session");
  if (existing) return existing;
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const created = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  sessionStorage.setItem("proofforge-demo-session", created);
  return created;
})();

function briefFromForm() {
  const values = new FormData(form);
  return {
    campaign_name: values.get("campaign_name"),
    audience: values.get("audience"),
    channel: values.get("channel"),
    message: values.get("message"),
    visual_style: values.get("visual_style"),
    brand_colors: ["#ff6034", "#3157ff"],
    forbidden_terms: ["unlicensed logos", "unsupported claims"],
    quality_threshold: Number(values.get("quality_threshold")),
    inject_weak_first: values.get("inject_weak_first") === "on"
  };
}

function runHeaders(extra = {}) {
  return currentAccessToken
    ? {...extra, "X-Proofforge-Run-Key": currentAccessToken}
    : extra;
}

function setBusy(busy) {
  isSubmitting = busy;
  submit.setAttribute("aria-disabled", busy ? "true" : "false");
  submit.setAttribute("aria-busy", busy ? "true" : "false");
  submit.querySelector("span").textContent = busy ? "Forging evidence..." : "Run evidence pipeline";
}

function showError(message) {
  const preserveCompletedResult = currentRun?.status === "completed" && !resultPanel.hidden;
  empty.hidden = preserveCompletedResult;
  resultPanel.hidden = !preserveCompletedResult;
  errorPanel.hidden = false;
  errorPanel.textContent = `${message} You can submit the brief again to retry a failed run.`;
  heading.textContent = preserveCompletedResult
    ? "New action failed; prior evidence preserved."
    : "Pipeline needs attention.";
}

async function authorizedFetch(path, options = {}) {
  const response = await fetch(path, {...options, headers: runHeaders(options.headers || {})});
  if (!response.ok) {
    let detail = `Request failed with HTTP ${response.status}.`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {
      // The status and endpoint still provide an actionable error.
    }
    throw new Error(detail);
  }
  return response;
}

async function renderRun(run) {
  currentRun = run;
  if (run.status === "failed") {
    showError(run.error || "The pipeline failed.");
    return;
  }
  if (run.status !== "completed") return;
  const receipt = run.result;
  if (!Array.isArray(receipt.orchestration.iterations)) {
    throw new Error("The orchestration trace has an invalid schema.");
  }
  const assetResponse = await authorizedFetch(`/api/runs/${run.id}/asset`);
  if (currentAssetObjectUrl) URL.revokeObjectURL(currentAssetObjectUrl);
  currentAssetObjectUrl = URL.createObjectURL(await assetResponse.blob());
  document.querySelector("#asset-preview").src = currentAssetObjectUrl;
  document.querySelector("#asset-mode").textContent = receipt.checks.publicDemoIsSynthetic
    ? "LOCAL SYNTHETIC DEMO"
    : "OPENAI + VERIFIED B2";
  document.querySelector("#manifest-hash").textContent = receipt.manifest.canonicalHash;
  document.querySelector("#object-key").textContent = receipt.storage.objectKey;
  document.querySelector("#integrity").textContent = receipt.checks.assetHashVerified
    ? "VERIFIED"
    : "FAILED";
  const trace = document.querySelector("#trace");
  trace.replaceChildren();
  receipt.orchestration.iterations.forEach((item) => {
    const article = document.createElement("article");
    article.className = item.passed ? "pass" : "fail";
    const iteration = document.createElement("span");
    iteration.textContent = `ITERATION ${item.index + 1}`;
    const score = document.createElement("strong");
    score.textContent = `${Math.round(item.score * 100)}%`;
    const feedback = document.createElement("small");
    feedback.textContent = item.passed ? "quality gate passed" : String(item.feedback || "");
    article.append(iteration, score, feedback);
    trace.append(article);
  });
  empty.hidden = true;
  errorPanel.hidden = true;
  resultPanel.hidden = false;
  heading.textContent = `${run.brief.campaign_name} / evidence ready`;
  approveButton.disabled = false;
  approveButton.textContent = "Record demo self-review";
  bundleButton.disabled = false;
  reviewStatus.textContent = "";
}

async function pollRun(runId) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const response = await authorizedFetch(`/api/runs/${runId}`);
    const run = await response.json();
    if (["completed", "failed"].includes(run.status)) return run;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  throw new Error("Pipeline timed out while the browser was waiting for a receipt.");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSubmitting) return;
  setBusy(true);
  errorPanel.hidden = true;
  heading.textContent = "Genblaze is evaluating the brief...";
  try {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Proofforge-Idempotency-Key": demoSessionKey
      },
      body: JSON.stringify({mode: "demo", brief: briefFromForm()})
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Could not start the pipeline.");
    currentAccessToken = payload.accessToken;
    await renderRun(await pollRun(payload.run.id));
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
});

approveButton.addEventListener("click", async () => {
  if (!currentRun) return;
  const reviewer = document.querySelector("#reviewer-name").value.trim();
  const notes = document.querySelector("#review-note").value.trim();
  if (reviewer.length < 2) {
    reviewStatus.textContent = "Enter a reviewer name with at least two characters.";
    document.querySelector("#reviewer-name").focus();
    return;
  }
  approveButton.disabled = true;
  try {
    const response = await authorizedFetch(`/api/runs/${currentRun.id}/review`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({approved: true, reviewer, notes})
    });
    const review = await response.json();
    approveButton.textContent = review.verified
      ? "Verified approval recorded ✓"
      : "Unverified self-review recorded ✓";
    reviewStatus.textContent = review.verified
      ? "Authenticated live approval recorded."
      : "Demo self-review recorded as unverified.";
  } catch (error) {
    reviewStatus.textContent = `Review failed: ${error.message}`;
    approveButton.disabled = false;
  }
});

bundleButton.addEventListener("click", async () => {
  if (!currentRun) return;
  bundleButton.disabled = true;
  reviewStatus.textContent = "Preparing evidence bundle download.";
  try {
    const response = await authorizedFetch(`/api/runs/${currentRun.id}/evidence.zip`);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `proofforge-${currentRun.id}.zip`;
    link.click();
    URL.revokeObjectURL(url);
    reviewStatus.textContent = "Evidence bundle download started.";
  } catch (error) {
    reviewStatus.textContent = `Evidence bundle download failed: ${error.message}`;
  } finally {
    bundleButton.disabled = false;
  }
});

fetch("/api/capabilities")
  .then((response) => response.json())
  .then(async (data) => {
    document.querySelector("#system-copy").textContent = data.liveReady
      ? "Operator B2 path configured"
      : "Local synthetic demo / B2 locked";
    if (!data.showcaseReady) return;
    const response = await fetch("/api/showcase");
    if (!response.ok) throw new Error(`Showcase request failed with HTTP ${response.status}.`);
    const showcase = await response.json();
    const panel = document.querySelector("#live-showcase");
    document.querySelector("#showcase-copy").textContent = `${showcase.campaign} passed its quality gate, was stored, retrieved, and hash-verified.`;
    document.querySelector("#showcase-hash").textContent = showcase.asset.sha256;
    document.querySelector("#showcase-iterations").textContent = String(showcase.orchestration.iterations.length);
    document.querySelector("#showcase-approval").textContent = `Verified by ${showcase.approval.reviewer}`;
    document.querySelector("#showcase-image").src = "/api/showcase/asset";
    panel.hidden = false;
    document.querySelector("#system-copy").textContent = "Verified live B2 showcase published";
  })
  .catch(() => {
    document.querySelector("#system-copy").textContent = "Capability check unavailable";
  });
