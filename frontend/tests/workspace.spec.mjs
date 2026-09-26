import { test, expect } from "@playwright/test";
import { resolve } from "node:path";
import { mkdir } from "node:fs/promises";

const baseDocument = {
  document_id: "ready-a",
  original_filename: "Product.pdf",
  status: "ready",
  stage: "ready",
  error: null,
  warnings: [],
  parsing: null,
};
const json = (route, value, status = 200) =>
  route.fulfill({ status, json: value });

test("real Docker upload: independent IDs, durable list and honest parse failure", async ({
  page,
  request,
}) => {
  test.skip(
    !process.env.M24_PDF,
    "Set M24_PDF to an existing development PDF; no held-out material.",
  );
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Start with your documents." }),
  ).toBeVisible();
  await page.screenshot({
    path: "../tmp/m24-acceptance/desktop.png",
    fullPage: true,
  });
  const before = await (await request.get("/api/documents")).json();
  const ids = [];
  for (let i = 0; i < 2; i++) {
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/documents") && r.request().method() === "POST",
    );
    await page
      .getByLabel("Upload files", { exact: true })
      .setInputFiles(process.env.M24_PDF);
    const received = await response;
    expect(received.status()).toBe(202);
    const body = await received.json();
    expect(body.status).toBe("queued");
    ids.push(body.document_id);
  }
  expect(ids[0]).not.toBe(ids[1]);
  await expect
    .poll(async () => {
      const rows = await (await request.get("/api/documents")).json();
      return rows
        .filter((row) => ids.includes(row.document_id))
        .map((row) => row.error?.code);
    })
    .toEqual(["retrieval_not_configured", "retrieval_not_configured"]);
  await expect(
    page.locator(".document").filter({ hasText: `#${ids[0].slice(0, 8)}` }),
  ).toContainText("extracted passages");
  await expect(
    page
      .locator(".document")
      .filter({ hasText: `#${ids[1].slice(0, 8)}` })
      .getByRole("checkbox"),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Retry processing", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "../tmp/m24-acceptance/uploaded.png",
    fullPage: true,
  });
  let postsAfterRefresh = 0;
  page.on("request", (req) => {
    if (req.method() === "POST") postsAfterRefresh++;
  });
  await page.reload();
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await expect(page.locator(".document")).toHaveCount(before.length + 2);
  expect(postsAfterRefresh).toBe(0);
  expect(
    (await request.get(`/api/documents/${ids[0]}/evidence`)).status(),
  ).toBe(409);
  expect(errors).toEqual([]);
});

test("controlled HTTP: scope by ID, quota waiting, retry gate and evidence pagination", async ({
  page,
}) => {
  let docs = [
    baseDocument,
    { ...baseDocument, document_id: "ready-b" },
    {
      ...baseDocument,
      document_id: "waiting",
      status: "processing",
      stage: "waiting_rate_limit",
    },
    {
      ...baseDocument,
      document_id: "retry",
      status: "failed",
      error: { message: "Processing was interrupted.", retryable: true },
    },
  ];
  const evidenceRequests = [];
  await page.route("**/api/documents", (route) => json(route, docs));
  await page.route("**/api/documents/retry/retry", (route) => {
    docs = docs.map((doc) =>
      doc.document_id === "retry"
        ? { ...doc, status: "queued", stage: "queued", error: null }
        : doc,
    );
    return json(route, docs[3], 202);
  });
  await page.route("**/api/documents/*/evidence?*", (route) => {
    const url = new URL(route.request().url());
    evidenceRequests.push(url.pathname + url.search);
    const offset = Number(url.searchParams.get("offset"));
    return json(
      route,
      Array.from({ length: offset === 0 ? 20 : 1 }, (_, n) => ({
        evidence_id: `e${offset + n}`,
        text: `Passage ${offset + n + 1}`,
        locator: { kind: "pdf", page_number: offset + n + 1 },
      })),
    );
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await expect(page.locator(".scope-line")).toContainText("Waiting for quota");
  const checkboxes = page.getByRole("checkbox");
  await checkboxes.nth(1).check();
  await expect(checkboxes.nth(0)).not.toBeChecked();
  await expect(checkboxes.nth(2)).toBeDisabled();
  await expect(page.locator(".scope-line")).toContainText(
    "1 materials selected",
  );
  await page
    .getByRole("button", { name: "Retry processing", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Retry processing", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "View evidence", exact: true })
    .nth(1)
    .click();
  await expect(page.getByText("Passage 1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Passage 21", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByText("Passage 1", { exact: true })).toBeVisible();
  expect(
    evidenceRequests.every((url) => url.includes("/ready-b/evidence")),
  ).toBeTruthy();
  expect(evidenceRequests).toContain(
    "/api/documents/ready-b/evidence?offset=20&limit=20",
  );
});

test("network failure is visible outside sidebar and refresh recovers", async ({
  page,
}) => {
  let offline = true;
  await page.route("**/api/documents", (route) =>
    offline ? route.abort() : json(route, []),
  );
  await page.goto("/");
  await expect(page.locator("main").getByRole("alert")).toContainText(
    "Cannot reach the server",
  );
  offline = false;
  await page.getByRole("button", { name: "View details", exact: true }).click();
  await page
    .getByRole("button", { name: "Refresh materials", exact: true })
    .click();
  await expect(
    page.getByText("No materials yet.", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
});

test("folder review skips unsupported files and sends only after confirmation", async ({
  page,
}, testInfo) => {
  const folder = testInfo.outputPath("folder");
  const { writeFile } = await import("node:fs/promises");
  await mkdir(folder, { recursive: true });
  await writeFile(resolve(folder, "prices.csv"), "order,price\n001,10\n");
  await writeFile(resolve(folder, "notes.txt"), "not uploaded");
  let uploads = 0;
  await page.route("**/api/documents", (route) => {
    if (route.request().method() === "POST") {
      uploads++;
      return json(route, { document_id: "new", status: "queued" }, 202);
    }
    return json(route, []);
  });
  await page.goto("/");
  await page.getByLabel("Upload folder", { exact: true }).setInputFiles(folder);
  await expect(page.getByRole("dialog")).toContainText("1 supported files");
  await expect(page.getByRole("dialog")).toContainText("PDF or CSV only");
  expect(uploads).toBe(0);
  await page
    .getByRole("button", { name: "Upload supported files", exact: true })
    .click();
  await expect(
    page.getByText("Received · processing is separate"),
  ).toBeVisible();
  expect(uploads).toBe(1);
});

test("drag upload and invalid local files do not silently disappear", async ({
  page,
}) => {
  let uploads = 0;
  await page.route("**/api/documents", (route) => {
    if (route.request().method() === "POST") {
      uploads++;
      return json(route, { document_id: "new", status: "queued" }, 202);
    }
    return json(route, []);
  });
  await page.goto("/");
  const dataTransfer = await page.evaluateHandle(() => {
    const data = new DataTransfer();
    data.items.add(
      new File(["order,price\n001,10"], "prices.csv", { type: "text/csv" }),
    );
    return data;
  });
  await page.locator(".app").dispatchEvent("dragenter", { dataTransfer });
  await expect(page.getByText("Drop your materials here")).toBeVisible();
  await page.locator(".app").dispatchEvent("drop", { dataTransfer });
  await expect(
    page.getByText("Received · processing is separate"),
  ).toBeVisible();
  await page
    .getByLabel("Upload files", { exact: true })
    .setInputFiles({
      name: "wrong.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("no"),
    });
  await expect(page.getByText("PDF or CSV only")).toBeVisible();
  await expect(page.locator("main").getByRole("alert")).toContainText(
    "Some files were not uploaded",
  );
  expect(uploads).toBe(1);
});

test("mobile layout and keyboard: drawer closes with Escape and restores focus", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/documents", (route) => json(route, []));
  await page.goto("/");
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Show sidebar", exact: true }),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../tmp/m24-acceptance/mobile.png",
    fullPage: true,
  });
});

test("new upload keeps existing ready selection while polling to a terminal failure", async ({
  page,
}) => {
  let uploaded = false,
    polls = 0;
  await page.route("**/api/documents", (route) => {
    if (route.request().method() === "POST") {
      uploaded = true;
      return json(route, { document_id: "new", status: "queued" }, 202);
    }
    const docs = [baseDocument];
    if (uploaded) {
      polls++;
      docs.push({
        ...baseDocument,
        document_id: "new",
        original_filename: "new.csv",
        status: polls < 3 ? "processing" : "failed",
        stage: polls < 3 ? "parsing" : "failed",
        error:
          polls < 3
            ? null
            : {
                message: "Document processing is not configured in this build.",
                retryable: false,
              },
      });
    }
    return json(route, docs);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await page.getByRole("checkbox").check();
  await page
    .getByLabel("Upload files", { exact: true })
    .setInputFiles({
      name: "new.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("id\n001"),
    });
  await expect(
    page.getByText("Reading document", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Not available", { exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox").nth(0)).toBeChecked();
  await expect(page.getByRole("checkbox").nth(1)).toBeDisabled();
});

test("server rejection is actionable and never automatically reuploads", async ({
  page,
}) => {
  let posts = 0;
  await page.route("**/api/documents", (route) => {
    if (route.request().method() === "POST") {
      posts++;
      return json(
        route,
        {
          error: {
            message: "Workspace is full.",
            code: "capacity_reached",
            retryable: false,
          },
        },
        409,
      );
    }
    return json(route, []);
  });
  await page.goto("/");
  await page
    .getByLabel("Upload files", { exact: true })
    .setInputFiles({
      name: "new.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("id\n001"),
    });
  await expect(
    page.getByText("Workspace is full.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Refresh materials", exact: true })
    .click();
  await expect(
    page.getByText("No materials yet.", { exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
});

test("evidence withdrawn by the server never leaves a successful preview", async ({
  page,
}) => {
  await page.route("**/api/documents", (route) => json(route, [baseDocument]));
  await page.route("**/api/documents/*/evidence?*", (route) =>
    json(
      route,
      { error: { message: "The document is not available for queries." } },
      409,
    ),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Show sidebar", exact: true }).click();
  await page
    .getByRole("button", { name: "View evidence", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Source evidence" }).getByRole("alert"),
  ).toContainText("not available");
  await expect(page.locator(".evidence")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled();
});
