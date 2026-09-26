import { test, expect } from "@playwright/test";

test("real proxy preserves HTTP errors and does not turn API failures into the SPA", async ({
  request,
}) => {
  test.skip(
    !process.env.M24_REAL_PROXY,
    "Set M24_REAL_PROXY=1 for isolated Docker proxy checks.",
  );
  const health = await request.get("/api/health");
  expect(health.status()).toBe(200);
  expect(await health.json()).toEqual({ status: "ok", version: "0.1.0" });
  const missing = await request.get("/api/documents/not-a-document");
  expect(missing.status()).toBe(404);
  expect((await missing.json()).error.code).toBe("document_not_found");
  const unsupported = await request.post("/api/documents", {
    multipart: {
      file: {
        name: "unsupported.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("not a supported file"),
      },
    },
  });
  expect(unsupported.status()).toBe(415);
  const oversized = await request.post("/api/documents", {
    multipart: {
      file: {
        name: "too-large.csv",
        mimeType: "text/csv",
        buffer: Buffer.alloc(20 * 1024 * 1024 + 1, 65),
      },
    },
  });
  expect(oversized.status()).toBe(413);
  expect((await oversized.json()).error.code).toBe("file_too_large");
});
