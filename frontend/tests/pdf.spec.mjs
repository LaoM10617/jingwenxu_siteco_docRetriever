import { test, expect } from "@playwright/test";
import { readFile, writeFile, mkdir } from "node:fs/promises";

const artifact = "../tmp/m26-docker/browser-result.json";
const questions = [
  "Compare Rondel order numbers 0MD5307L1830 and 0MD5307L0940.",
  "What is the part number for the Rondel HF movement sensor?",
];

test("real Docker PDF: ready, original evidence and development retrieval", async ({ page, request }) => {
  test.skip(!process.env.M26_PDF, "Requires short development PDF and isolated acceptance adapter.");
  test.setTimeout(180_000);
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await mkdir("../tmp/m26-docker", { recursive: true });
  await page.goto("/");
  const upload = page.waitForResponse(r => r.url().endsWith("/api/documents") && r.request().method() === "POST");
  await page.getByLabel("Upload files", { exact: true }).setInputFiles(process.env.M26_PDF);
  const accepted = await upload;
  expect(accepted.status()).toBe(202);
  const id = (await accepted.json()).document_id;
  const stages = [];
  await expect.poll(async () => {
    const status = await (await request.get(`/api/documents/${id}`)).json();
    stages.push(status.stage);
    return status.status;
  }, { timeout: 100_000 }).toBe("ready");
  const status = await (await request.get(`/api/documents/${id}`)).json();
  expect(status.parsing.page_count).toBe(2);
  expect(status.parsing.evidence_count).toBe(17);
  expect(status.warnings).toHaveLength(1);
  const card = page.locator(".document").filter({ hasText: `#${id.slice(0, 8)}` });
  await expect(card).toContainText("Ready");
  await card.getByRole("checkbox").check();
  await card.getByRole("button", { name: "View evidence", exact: true }).click();
  await expect(page.locator(".evidence")).toHaveCount(17);
  await expect(page.getByText("page number: 2", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: "../tmp/m26-docker/pdf-evidence.png", fullPage: true });
  const results = [];
  for (const question of questions) {
    const response = await request.post("/api/acceptance/retrieve", {
      data: { question, document_ids: [id] }, timeout: 110_000,
    });
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.records.length).toBe(8);
    expect(result.routes.semantic.count).toBe(17);
    expect(result.records.every(row => row.document_id === id && row.locator.kind === "pdf")).toBe(true);
    results.push(result);
  }
  const metrics = await (await request.get("/api/acceptance/calls")).json();
  expect(metrics.calls.map(call => call.input_type)).toEqual(["document", "query", "query"]);
  for (let i = 1; i < metrics.calls.length; i++) {
    expect(metrics.calls[i].started - metrics.calls[i - 1].started).toBeGreaterThanOrEqual(19.9);
  }
  await writeFile(artifact, JSON.stringify({ id, status, stages, results, metrics }, null, 2));
  await page.reload();
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await expect(page.locator(".document").filter({ hasText: `#${id.slice(0, 8)}` })).toContainText("Ready");
  expect(errors).toEqual([]);
});

test("real Docker PDF: restart uses persisted vectors and cached query embeddings", async ({ page, request }) => {
  test.skip(!process.env.M26_RESTART, "Run after restart with provider forbidden.");
  const before = JSON.parse(await readFile(artifact, "utf8"));
  expect(await (await request.get(`/api/documents/${before.id}`)).json()).toEqual(before.status);
  for (let i = 0; i < questions.length; i++) {
    const response = await request.post("/api/acceptance/retrieve", { data: { question: questions[i], document_ids: [before.id] } });
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual(before.results[i]);
  }
  const metrics = await (await request.get("/api/acceptance/calls")).json();
  expect(metrics.process_started).toBeGreaterThan(before.metrics.process_started);
  expect(metrics.calls).toEqual([]);
  await writeFile("../tmp/m26-docker/restart-result.json", JSON.stringify(metrics, null, 2));
  await page.goto("/");
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await expect(page.locator(".document").filter({ hasText: `#${before.id.slice(0, 8)}` })).toContainText("Ready");
});
