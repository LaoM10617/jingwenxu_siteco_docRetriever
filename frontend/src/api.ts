export type Document = {
  document_id: string;
  original_filename: string;
  status: "queued" | "processing" | "ready" | "failed";
  stage: string;
  error: { code: string; message: string; retryable: boolean } | null;
  warnings: { page_number: number; code: string; message: string }[];
  parsing: null | {
    page_count: number | null;
    evidence_count: number;
    coverage_limited: boolean;
    coverage: Record<"extracted" | "degraded" | "no_text" | "failed", number>;
  };
};

export type Evidence = {
  evidence_id: string;
  text: string;
  locator: Record<string, unknown>;
  raw_values?: unknown;
};

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const timeout = AbortSignal.timeout(
    init.method === "POST" ? 120_000 : 15_000,
  );
  const signal = init.signal
    ? AbortSignal.any([init.signal, timeout])
    : timeout;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, signal });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new Error(
      init.method === "POST"
        ? "Connection interrupted. Check the material list before trying again; the server may have received your request."
        : "Cannot reach the server. The displayed list may be out of date.",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.error?.message === "string"
        ? body.error.message
        : `Request failed (${response.status}). Please try again later.`,
    );
  }
  return response.json();
}

export function statusLabel(doc: Document): string {
  if (doc.status === "ready") return "Ready";
  if (doc.status === "failed") return "Not available";
  if (doc.status === "queued") return "Queued";
  return (
    {
      parsing: "Reading document",
      embedding: "Preparing search",
      waiting_rate_limit: "Waiting for quota",
      indexing: "Building index",
    }[doc.stage] ?? "Processing"
  );
}

export function fileProblem(file: File): string | null {
  if (!/\.(pdf|csv)$/i.test(file.name)) return "PDF or CSV only";
  if (!file.size) return "Empty file";
  if (file.size > 20 * 1024 * 1024) return "Larger than 20 MiB";
  return null;
}
