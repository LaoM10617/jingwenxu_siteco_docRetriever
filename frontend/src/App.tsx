import { useEffect, useRef, useState } from "react";
import { fileProblem, request, statusLabel, type Document } from "./api";
import EvidencePanel from "./EvidencePanel";
import ChatThread from "./ChatThread";
import { useChat } from "./useChat";

type Upload = {
  id: number;
  name: string;
  state: "waiting" | "uploading" | "received" | "error";
  message?: string;
};
type Tab = "materials" | "history" | "settings";

function Icon({ kind }: { kind: "panel" | "file" | "plus" | "arrow" }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {kind === "panel" && (
        <>
          <rect x="3" y="4" width="18" height="16" rx="3" />
          <path d="M9 4v16" />
        </>
      )}
      {kind === "file" && (
        <>
          <path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10Z" />
          <path d="M13 3v7h7M8 14h8M8 17h5" />
        </>
      )}
      {kind === "plus" && <path d="M12 5v14M5 12h14" />}
      {kind === "arrow" && <path d="m6 11 6-6 6 6M12 5v14" />}
    </svg>
  );
}

export default function App() {
  const chat = useChat();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [listError, setListError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [sidebar, setSidebar] = useState(false);
  const [narrow, setNarrow] = useState(
    () => window.matchMedia("(max-width: 900px)").matches,
  );
  const [tab, setTab] = useState<Tab>("materials");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [folder, setFolder] = useState<File[] | null>(null);
  const [dragging, setDragging] = useState(false);
  const [retrying, setRetrying] = useState<string[]>([]);
  const [actionError, setActionError] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const folderDialog = useRef<HTMLDialogElement>(null);
  const sidebarToggle = useRef<HTMLButtonElement>(null);
  const sidebarPanel = useRef<HTMLElement>(null);
  const uploadQueue = useRef(Promise.resolve());
  const uploadId = useRef(0);
  const dragDepth = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await request<Document[]>("/documents", {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setDocuments(result);
        setListError("");
        setLoaded(true);
        setSelected((ids) =>
          ids.filter((id) =>
            result.some((d) => d.document_id === id && d.status === "ready"),
          ),
        );
        if (
          result.some((d) => d.status === "queued" || d.status === "processing")
        )
          timer = setTimeout(poll, 1000);
      } catch (error) {
        if (!controller.signal.aborted) {
          setListError(
            error instanceof Error ? error.message : "Cannot load materials.",
          );
          timer = setTimeout(poll, 5000);
        }
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [refresh]);

  useEffect(() => {
    const reload = () => setRefresh((n) => n + 1);
    window.addEventListener("focus", reload);
    return () => window.removeEventListener("focus", reload);
  }, []);

  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);
  useEffect(() => {
    if (folder) folderDialog.current?.showModal();
  }, [folder]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const resize = () => setNarrow(media.matches);
    media.addEventListener("change", resize);
    return () => media.removeEventListener("change", resize);
  }, []);

  useEffect(() => {
    if (!sidebar) return;
    sidebarPanel.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (folderDialog.current?.open) return;
      if (event.key === "Escape") {
        setSidebar(false);
        sidebarToggle.current?.focus();
      }
      if (narrow && event.key === "Tab") {
        const elements = sidebarPanel.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), summary",
        );
        if (!elements?.length) return;
        const first = elements[0],
          last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [sidebar, narrow]);

  const activeUploads = uploads.filter(
    (u) => u.state === "waiting" || u.state === "uploading",
  );
  const occupied = documents.filter((d) => d.status !== "failed").length;
  const availableSlots = Math.max(0, 10 - occupied - activeUploads.length);
  const processing = documents.filter(
    (d) => d.status === "queued" || d.status === "processing",
  );
  const failed = documents.filter((d) => d.status === "failed");
  const waitingQuota = processing.some((d) => d.stage === "waiting_rate_limit");
  const currentPreview = documents.find(
    (d) => d.document_id === preview && d.status === "ready",
  );

  function showMaterials() {
    setSidebar(true);
    setTab("materials");
  }

  function addFiles(files: File[]) {
    showMaterials();
    const additions = files.map((file) => ({
      id: ++uploadId.current,
      name: file.name,
      state: "waiting" as const,
    }));
    setUploads((previous) => [...previous, ...additions]);
    files.forEach((file, index) => {
      const id = additions[index].id;
      const update = (state: Upload["state"], message?: string) =>
        setUploads((previous) =>
          previous.map((u) => (u.id === id ? { ...u, state, message } : u)),
        );
      const problem = fileProblem(file);
      if (problem) {
        update("error", problem);
        return;
      }
      // Serialize reception, while allowing another batch to be added at any time.
      uploadQueue.current = uploadQueue.current.then(async () => {
        update("uploading");
        try {
          const body = new FormData();
          body.append("file", file);
          await request("/documents", { method: "POST", body });
          update("received");
        } catch (error) {
          update(
            "error",
            error instanceof Error ? error.message : "Upload failed.",
          );
        } finally {
          setRefresh((n) => n + 1);
        }
      });
    });
  }

  async function retry(doc: Document) {
    if (retrying.includes(doc.document_id)) return;
    setRetrying((ids) => [...ids, doc.document_id]);
    setActionError("");
    try {
      await request(`/documents/${encodeURIComponent(doc.document_id)}/retry`, {
        method: "POST",
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Retry failed.");
    } finally {
      setRetrying((ids) => ids.filter((id) => id !== doc.document_id));
      setRefresh((n) => n + 1);
    }
  }

  return (
    <div
      className={`app ${sidebar ? "sidebar-open" : ""}`}
      onDragEnter={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          dragDepth.current++;
          setDragging(true);
        }
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) event.preventDefault();
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        if (--dragDepth.current <= 0) {
          dragDepth.current = 0;
          setDragging(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
        const files = Array.from(event.dataTransfer.files);
        if (files.length) addFiles(files);
        else
          setActionError(
            "For folders, use Choose folder in the attachment menu.",
          );
      }}
    >
      <header className="topbar">
        <div className="brand-group">
          <button
            className="icon-button"
            aria-label={sidebar ? "Hide sidebar" : "Show sidebar"}
            aria-expanded={sidebar}
            aria-controls="sidebar"
            ref={sidebarToggle}
            onClick={() => setSidebar(!sidebar)}
          >
            <Icon kind="panel" />
          </button>
          <a className="brand" href="./">
            SITECO<span>Document chat</span>
          </a>
        </div>
        <button className="materials-toggle" onClick={showMaterials}>
          <Icon kind="file" />
          Materials <span className="count">{documents.length}</span>
        </button>
      </header>

      {sidebar && (
        <button
          className="sidebar-backdrop"
          aria-label="Close sidebar"
          onClick={() => setSidebar(false)}
        />
      )}
      <aside
        ref={sidebarPanel}
        id="sidebar"
        className="sidebar"
        inert={!sidebar}
        aria-label="Workspace"
      >
        <nav className="tabs" aria-label="Workspace sections">
          {(["materials", "history", "settings"] as const).map((value) => (
            <button
              key={value}
              aria-current={tab === value ? "page" : undefined}
              onClick={() => setTab(value)}
            >
              {value[0].toUpperCase() + value.slice(1)}
            </button>
          ))}
        </nav>
        {tab === "materials" && (
          <>
            <div className="section-heading">
              <h2>Your materials</h2>
              <button
                className="icon-button"
                onClick={() => setRefresh((n) => n + 1)}
                aria-label="Refresh materials"
              >
                ↻
              </button>
            </div>
            <p className="muted">
              Select ready materials to set the scope of your questions.
            </p>
            {listError && (
              <p role="alert" className="error">
                {listError}
              </p>
            )}
            {!loaded && !listError && <p role="status">Loading materials…</p>}
            {loaded && documents.length === 0 && (
              <div className="empty-materials">
                <Icon kind="file" />
                <p>No materials yet.</p>
                <button onClick={() => fileInput.current?.click()}>
                  Choose files
                </button>
              </div>
            )}
            {documents.map((doc) => (
              <article className="document" key={doc.document_id}>
                <label className="document-name">
                  <input
                    type="checkbox"
                    disabled={doc.status !== "ready" || !!listError}
                    checked={selected.includes(doc.document_id)}
                    onChange={(event) =>
                      setSelected((ids) =>
                        event.target.checked
                          ? [...ids, doc.document_id]
                          : ids.filter((id) => id !== doc.document_id),
                      )
                    }
                  />
                  <span>{doc.original_filename}</span>
                </label>
                <div className="document-meta">
                  <span className={`status ${doc.status}`}>
                    {statusLabel(doc)}
                  </span>
                  <span title={doc.document_id}>
                    #{doc.document_id.slice(0, 8)}
                  </span>
                </div>
                {doc.stage === "waiting_rate_limit" && (
                  <p className="muted">
                    Waiting for the shared model quota. Your ready materials
                    remain available.
                  </p>
                )}
                {doc.error && <p className="error">{doc.error.message}</p>}
                {doc.status === "failed" && doc.error?.retryable && (
                  <button
                    disabled={retrying.includes(doc.document_id)}
                    onClick={() => void retry(doc)}
                  >
                    {retrying.includes(doc.document_id)
                      ? "Requesting retry…"
                      : "Retry processing"}
                  </button>
                )}
                {doc.parsing?.kind === "csv" && (
                  <details>
                    <summary>{doc.parsing.record_count} records · {doc.parsing.indexed_record_count} with order IDs</summary>
                    <p className="muted">
                      Prices: {doc.parsing.price_counts.valid} valid, {doc.parsing.price_counts.missing} missing, {doc.parsing.price_counts.invalid} invalid.
                      Original values and duplicate records are retained.
                    </p>
                  </details>
                )}
                {doc.parsing && doc.parsing.kind !== "csv" && (
                  <details>
                    <summary>
                      {doc.parsing.evidence_count} extracted passages ·{" "}
                      {doc.parsing.page_count == null
                        ? "Page count unknown"
                        : `${doc.parsing.page_count} pages`}
                    </summary>
                    <p className="muted">
                      Page coverage: {doc.parsing.coverage.extracted} extracted,{" "}
                      {doc.parsing.coverage.degraded} degraded,{" "}
                      {doc.parsing.coverage.no_text} without text,{" "}
                      {doc.parsing.coverage.failed} failed.
                    </p>
                    <p className="muted">
                      Coverage describes extraction, not accuracy or
                      completeness.
                    </p>
                  </details>
                )}
                {doc.warnings.length > 0 && (
                  <details className="warnings">
                    <summary>{doc.warnings.length} extraction warnings</summary>
                    <ul>
                      {doc.warnings.map((warning, index) => (
                        <li key={index}>
                          {warning.record_number != null
                            ? `Record ${warning.record_number} (${warning.column})`
                            : `Page ${warning.page_number}`}: {warning.message}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
                {doc.status === "ready" && (
                  <button
                    disabled={!!listError}
                    onClick={() => {
                      setPreview(doc.document_id);
                      setSidebar(false);
                    }}
                  >
                    View evidence
                  </button>
                )}
              </article>
            ))}
            {uploads.length > 0 && (
              <section className="upload-activity">
                <div className="section-heading">
                  <h3>Upload activity</h3>
                  <button
                    onClick={() =>
                      setUploads((items) =>
                        items.filter(
                          (u) =>
                            u.state === "waiting" || u.state === "uploading",
                        ),
                      )
                    }
                  >
                    Clear finished
                  </button>
                </div>
                {uploads.map((upload) => (
                  <div key={upload.id} className="upload-item">
                    <span className="filename">{upload.name}</span>
                    <span
                      className={upload.state === "error" ? "error" : "muted"}
                    >
                      {upload.message ??
                        {
                          waiting: "Waiting to upload",
                          uploading: "Uploading…",
                          received: "Received · processing is separate",
                          error: "Upload failed",
                        }[upload.state]}
                    </span>
                  </div>
                ))}
              </section>
            )}
            <p className="sidebar-footnote">
              PDF / CSV · 20 MiB each
              <br />
              Up to 10 active materials. Files persist after refresh; selection
              is for this page only.
            </p>
          </>
        )}
        {tab === "history" && (
          <section>
            <h2>Conversation history</h2>
            <p className="muted">
              This tab keeps the current conversation temporarily so you can refresh and resume a question.
            </p>
            <p className="muted">
              Long-term saved conversations are not available. Each question is answered independently.
            </p>
          </section>
        )}
        {tab === "settings" && (
          <section>
            <h2>Settings</h2>
            <p className="muted">
              Provider configuration is managed by the server in this build.
              Personal API key settings are not available yet.
            </p>
            <p className="muted">
              Your browser does not receive server credentials.
            </p>
          </section>
        )}
      </aside>

      <main inert={sidebar && narrow}>
        <div className="conversation-heading">
          <span>Document conversation</span>
          <button onClick={() => {chat.newConversation(); setSelected([]); setPreview(null);}}>New conversation</button>
        </div>
        {currentPreview ? (
          <EvidencePanel
            key={currentPreview.document_id}
            document={currentPreview}
            close={() => setPreview(null)}
          />
        ) : chat.chat.turns.length ? (
          <ChatThread turns={chat.chat.turns} retry={chat.submit} refresh={chat.refresh} />
        ) : (
          <section className="welcome">
            <div className="document-mark">
              <Icon kind="file" />
            </div>
            <h1>Start with your documents.</h1>
            <p>
              Add product information, terms or a price list.
              <br />
              Keep the evidence close to the conversation.
            </p>
            <button
              className="primary"
              onClick={() => fileInput.current?.click()}
            >
              <Icon kind="plus" />
              Add materials
            </button>
            <p className="drop-hint">or drop PDF and CSV files anywhere here</p>
          </section>
        )}
        <div className="composer-area">
          <div className="scope-line">
            <button onClick={showMaterials}>
              {selected.length} materials selected
            </button>
            <span role="status">
              {activeUploads.length
                ? `${activeUploads.length} uploading or waiting`
                : waitingQuota
                  ? "Waiting for quota"
                  : processing.length
                    ? `${processing.length} processing`
                    : failed.length
                      ? `${failed.length} unavailable — see materials`
                      : selected.length ? "Ready to ask about selected materials" : "Select ready materials to ask questions"}
            </span>
          </div>
          {(listError ||
            actionError ||
            uploads.some((u) => u.state === "error")) && (
            <div className="notice" role="alert">
              {actionError ||
                listError ||
                "Some files were not uploaded. Check upload activity."}{" "}
              <button onClick={showMaterials}>View details</button>
            </div>
          )}
          <div className="composer">
            <textarea
              aria-label="Message"
              value={chat.message}
              maxLength={8000}
              onChange={event => chat.setMessage(event.target.value)}
              placeholder="Ask about your documents"
              rows={2}
            />
            <div className="composer-tools">
              <details className="attach-menu">
                <summary aria-label="Add attachments">
                  <Icon kind="plus" />
                  <span>Attach</span>
                </summary>
                <div className="attach-options">
                  <button onClick={() => fileInput.current?.click()}>
                    Choose files
                  </button>
                  <button onClick={() => folderInput.current?.click()}>
                    Choose folder
                  </button>
                </div>
              </details>
              <button
                className="send-button"
                disabled={chat.busy || !chat.message.trim() || !selected.length || !!listError || chat.chat.turns.length >= 50}
                onClick={() => {setPreview(null); chat.send(selected, selected.map(id => documents.find(d => d.document_id === id)?.original_filename || id));}}
                aria-label="Send message"
              >
                <Icon kind="arrow" />
              </button>
            </div>
          </div>
          <p className="composer-note">
            Each question uses the selected materials independently. Include full product or order numbers.
            {chat.chat.turns.length >= 50 && ' Start a new conversation to ask more questions.'}
          </p>
        </div>
      </main>
      <input
        ref={fileInput}
        type="file"
        multiple
        accept=".pdf,.csv"
        aria-label="Upload files"
        className="visually-hidden"
        tabIndex={-1}
        onChange={(event) => {
          addFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      <input
        ref={folderInput}
        type="file"
        multiple
        aria-label="Upload folder"
        className="visually-hidden"
        tabIndex={-1}
        onChange={(event) => {
          setFolder(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      {dragging && (
        <div className="drop-overlay">
          <Icon kind="plus" />
          <h2>Drop your materials here</h2>
          <p>PDF and CSV · up to 20 MiB each</p>
        </div>
      )}
      <dialog
        ref={folderDialog}
        onCancel={() => setFolder(null)}
        aria-labelledby="folder-title"
      >
        <h2 id="folder-title">Review folder upload</h2>
        <p>
          {folder?.filter((file) => !fileProblem(file)).length ?? 0} supported
          files. {availableSlots} active slots currently available.
        </p>
        <p className="muted">
          Each file is uploaded separately. Folder paths are not sent to the
          server.
        </p>
        <ul className="folder-list">
          {folder?.map((file, index) => (
            <li key={index}>
              <span>{file.webkitRelativePath || file.name}</span>
              <span className={fileProblem(file) ? "error" : "muted"}>
                {fileProblem(file) ?? "Ready to upload"}
              </span>
            </li>
          ))}
        </ul>
        <div className="dialog-actions">
          <button
            onClick={() => {
              folderDialog.current?.close();
              setFolder(null);
            }}
          >
            Cancel
          </button>
          <button
            className="primary"
            disabled={
              !folder?.some((file) => !fileProblem(file)) ||
              folder.filter((file) => !fileProblem(file)).length >
                availableSlots
            }
            onClick={() => {
              addFiles((folder ?? []).filter((file) => !fileProblem(file)));
              folderDialog.current?.close();
              setFolder(null);
            }}
          >
            Upload supported files
          </button>
        </div>
        {!!folder &&
          folder.filter((file) => !fileProblem(file)).length >
            availableSlots && (
            <p className="error">
              Too many files for the available slots. Cancel and choose fewer
              files instead.
            </p>
          )}
      </dialog>
    </div>
  );
}
