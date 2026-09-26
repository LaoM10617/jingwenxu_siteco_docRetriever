import { test, expect } from "@playwright/test";
import { writeFile, readFile, mkdir } from "node:fs/promises";

test("CSV summaries and warnings use records; missing prices stay explicit", async ({ page }) => {
  await page.route("**/api/documents", route => route.fulfill({ json: [{
    document_id: "csv-fixture", original_filename: "prices.csv", status: "ready", stage: "ready", error: null,
    parsing: { kind: "csv", record_count: 2, indexed_record_count: 2, price_counts: { valid: 1, missing: 0, invalid: 1 } },
    warnings: [{ record_number: 2, column: "Listenpreis", code: "price_invalid", message: "Original price retained; no numeric value." }],
  }] }));
  await page.route("**/api/documents/csv-fixture/evidence?*", route => route.fulfill({ json: [{
    evidence_id: "record-2", locator: { kind: "csv", record_number: 2 },
    text: "Bestellnummer: 001\nListenpreis: unknown", raw_values: ["001", "unknown"],
    headers: ["Bestellnummer", "Listenpreis"], price: null, price_status: "invalid",
  }] }));
  await page.goto("/");
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await expect(page.getByText("2 records · 2 with order IDs")).toBeVisible();
  await expect(page.getByText("extracted passages")).toHaveCount(0);
  await page.getByText("1 extraction warnings").click();
  await expect(page.getByText("Record 2 (Listenpreis):")).toBeVisible();
  await page.getByRole("button", { name: "View evidence", exact: true }).click();
  await expect(page.getByText("record number: 2", { exact: true })).toBeVisible();
  await expect(page.getByText("Price invalid: no numeric value available.", { exact: false })).toBeVisible();
  await expect(page.getByText("Bestellnummer: 001", { exact: false })).toBeVisible();
});

const artifact = "../tmp/m25-acceptance/browser-result.json";
const orders = ["51DB11EC11B1D", "51DB11EC11D1D", "NOT-A-SITECO-ORDER-000"];

test("real Docker CSV: upload complete file, page evidence, query development records", async ({ page, request }) => {
  test.skip(!process.env.M25_CSV, "Requires full development price_list and acceptance-only backend harness.");
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  const response = page.waitForResponse(r => r.url().endsWith("/api/documents") && r.request().method() === "POST");
  await page.getByLabel("Upload files", { exact: true }).setInputFiles(process.env.M25_CSV);
  const received = await response;
  expect(received.status()).toBe(202);
  const accepted = await received.json();
  expect(accepted.status).toBe("queued");
  const id = accepted.document_id;
  await expect.poll(async () => (await (await request.get(`/api/documents/${id}`)).json()).status).toBe("ready");
  const status = await (await request.get(`/api/documents/${id}`)).json();
  expect(status.parsing.record_count).toBe(11386);
  expect(status.warnings).toEqual([]);
  const card = page.locator(".document").filter({ hasText: `#${id.slice(0, 8)}` });
  await expect(card).toContainText("11386 records");
  await card.getByRole("checkbox").check();
  await card.getByRole("button", { name: "View evidence", exact: true }).click();
  await expect(page.getByText("record number: 1", { exact: true })).toBeVisible();
  await expect(page.locator(".evidence")).toHaveCount(20);
  await page.screenshot({ path: "../tmp/m25-acceptance/csv-evidence.png", fullPage: true });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("record number: 21", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByText("record number: 1", { exact: true })).toBeVisible();
  const lookup = await request.post("/api/acceptance/orders", { data: { order_ids: orders, document_ids: [id], limit: 1 } });
  expect(lookup.status()).toBe(200);
  const result = await lookup.json();
  expect(result.total).toBe(2);
  expect(result.has_more).toBe(true);
  expect(result.unmatched_order_ids).toEqual([orders[2]]);
  expect(result.records[0].locator.record_number).toBe(1);
  expect(result.records[0].price).toBe("183.20");
  const second = await (await request.post("/api/acceptance/orders", { data: { order_ids: orders, document_ids: [id], offset: 1, limit: 1 } })).json();
  expect(second.records[0].locator.record_number).toBe(2);
  expect(second.has_more).toBe(false);
  await mkdir("../tmp/m25-acceptance", { recursive: true });
  await writeFile(artifact, JSON.stringify({ id, status, result, second }, null, 2));
  await page.reload();
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await expect(page.locator(".document").filter({ hasText: `#${id.slice(0, 8)}` })).toContainText("11386 records");
  expect(errors).toEqual([]);
});

test("real Docker CSV: same exact results after backend recreation", async ({ request, page }) => {
  test.skip(!process.env.M25_RESTART, "Run separately after recreating backend.");
  const before = JSON.parse(await readFile(artifact, "utf-8"));
  expect(await (await request.get(`/api/documents/${before.id}`)).json()).toEqual(before.status);
  for (const offset of [0, 1]) {
    const result = await (await request.post("/api/acceptance/orders", { data: { order_ids: orders, document_ids: [before.id], offset, limit: 1 } })).json();
    expect(result).toEqual(offset ? before.second : before.result);
  }
  await page.goto("/");
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await expect(page.locator(".document").filter({ hasText: `#${before.id.slice(0, 8)}` })).toContainText("11386 records");
});
