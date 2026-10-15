/** Task-scoped QA prompt bridge for infer video describe (CLI has no --prompt). */
import { createHash } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

export async function qualityReviewPrompt(buffer: Buffer): Promise<string> {
  // OpenClaw's plugin loader may rewrite import.meta.url. The trusted caller
  // supplies the approved root; request data never chooses this boundary.
  const suppliedRoot = process.env.MANDALA_VIDEO_QA_PROJECT_ROOT;
  if (!suppliedRoot || !isAbsolute(suppliedRoot) || suppliedRoot.split(/[\\/]/).some(p => p === ".." || p.startsWith(".env"))) throw new Error("QA project root missing or unsafe");
  const ROOT = resolve(suppliedRoot);
  const supplied = process.env.MANDALA_VIDEO_QA_REQUEST_FILE;
  const receipt = process.env.MANDALA_VIDEO_QA_REQUEST_SHA256;
  if (!supplied || !receipt || !/^[a-f0-9]{64}$/.test(receipt)) throw new Error("QA request receipt missing");
  if (supplied.split(/[\\/]/).some(p => p === ".." || p.startsWith(".env"))) throw new Error("Unsafe QA request path");
  const path = resolve(ROOT, supplied);
  const local = relative(ROOT, path);
  if (isAbsolute(local) || local.startsWith(".." + sep) || local === "..") throw new Error("QA request outside project");
  for (let p = path; p !== dirname(p); p = dirname(p)) {
    if ((await lstat(p)).isSymbolicLink()) throw new Error("QA symlink rejected");
  }
  const info = await lstat(path);
  if (!info.isFile() || info.size > 131072) throw new Error("QA request file limit");
  const raw = await readFile(path);
  if (raw.length > 131072 || createHash("sha256").update(raw).digest("hex") !== receipt) throw new Error("QA request changed");
  const data = JSON.parse(raw.toString("utf8"));
  if (data.contract_version !== "0.1.0" || data.kind !== "stage56_multimodal_qa_request" ||
      !["edited_output", "original_source"].includes(data.media?.role) || data.media?.bytes !== buffer.length ||
      data.media?.sha256 !== createHash("sha256").update(buffer).digest("hex") ||
      typeof data.prompt !== "string" || !data.prompt.trim() || Buffer.byteLength(data.prompt) > 65536 ||
      data.prompt_sha256 !== createHash("sha256").update(data.prompt).digest("hex")) throw new Error("QA media/prompt binding invalid");
  if (/(?:\b(?:sk|gsk)-[A-Za-z0-9_-]{8,}|\bAIza[\w-]{16,}|Bearer\s+[\w.-]+)/i.test(data.prompt)) throw new Error("QA credential-like prompt rejected");
  return data.prompt;
}
