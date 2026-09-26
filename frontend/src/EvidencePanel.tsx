import { useEffect, useState } from "react";
import { request, type Document, type Evidence } from "./api";

const PAGE_SIZE = 20;

export default function EvidencePanel({
  document,
  close,
}: {
  document: Document;
  close: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setItems([]);
    request<Evidence[]>(
      `/documents/${encodeURIComponent(document.document_id)}/evidence?offset=${offset}&limit=${PAGE_SIZE}`,
      { signal: controller.signal },
    )
      .then((items) => {
        if (!controller.signal.aborted) setItems(items);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [document.document_id, offset, attempt]);

  return (
    <section className="evidence-panel" aria-label="Source evidence">
      <div className="section-heading">
        <h2>Source evidence</h2>
        <button onClick={close} aria-label="Close evidence">
          ×
        </button>
      </div>
      <p className="filename">{document.original_filename}</p>
      <p className="muted">
        Extracted text, not a complete representation of the original document.
      </p>
      {loading && <p role="status">Loading evidence…</p>}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        </div>
      )}
      {!loading && !error && items.length === 0 && <p>No more evidence.</p>}
      {items.map((item) => (
        <article className="evidence" key={item.evidence_id}>
          <div className="source-location">
            {Object.entries(item.locator).map(([key, value]) => (
              <span key={key}>
                {key.replaceAll("_", " ")}:{" "}
                {typeof value === "object"
                  ? JSON.stringify(value)
                  : String(value)}
              </span>
            ))}
          </div>
          <p className="source-text">{item.text}</p>
          {item.raw_values != null && (
            <details>
              <summary>Original values</summary>
              <pre>{JSON.stringify(item.raw_values, null, 2)}</pre>
            </details>
          )}
        </article>
      ))}
      <nav className="pagination" aria-label="Evidence pages">
        <button
          disabled={loading || offset === 0}
          onClick={() => setOffset((n) => Math.max(0, n - PAGE_SIZE))}
        >
          Previous
        </button>
        <span>Page {offset / PAGE_SIZE + 1}</span>
        <button
          disabled={loading || !!error || items.length < PAGE_SIZE}
          onClick={() => setOffset((n) => n + PAGE_SIZE)}
        >
          Next
        </button>
      </nav>
    </section>
  );
}
