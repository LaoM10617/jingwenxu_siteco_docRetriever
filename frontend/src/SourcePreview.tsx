import { useState } from 'react';
import { request } from './api';
import type { Source } from './useChat';

type Preview = {kind: 'pdf'; page_number: number; width: number; height: number; image: string;
  regions: {role: 'evidence' | 'context'; box: [number, number, number, number]}[]; notice: string | null}
  | {kind: 'csv'; record_number: number; headers: string[]; raw_values: string[]};

export default function SourcePreview({source}: {source: Source}) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [zoom, setZoom] = useState(1);
  async function load() {
    setLoading(true); setError(''); setPreview(null);
    try {
      setPreview(await request<Preview>(`/documents/${encodeURIComponent(source.document_id)}/evidence/${encodeURIComponent(source.evidence_id)}/preview`));
    } catch (e) { setError(e instanceof Error ? e.message : 'Cannot load the original source.'); }
    finally { setLoading(false); }
  }
  function toggle() {
    setOpen(!open);
    if (!open && !loading) void load();
  }
  return <div className="source-preview">
    <button onClick={toggle} aria-expanded={open}>{open ? 'Hide original source' : 'Open original source'}</button>
    {open && <section aria-label="Original source preview">
      {loading && <p role="status">Loading original source…</p>}
      {error && <div><p role="alert" className="error">{error} The citation text above remains available.</p>
        <button disabled={loading} onClick={() => void load()}>Retry preview</button></div>}
      {preview?.kind === 'pdf' && <>
        <p>Page {preview.page_number} · {source.original_filename || 'Original PDF'}</p>
        {preview.notice ? <p className="notice">{preview.notice}</p>
          : <p className="preview-legend"><span className="legend-evidence">Evidence region</span>
            <span className="legend-context">Context / headings</span></p>}
        <p className="muted">Regions show where the source came from; they do not prove the answer is correct.</p>
        <div className="preview-controls">
          <button aria-label="Zoom out" disabled={zoom === 1} onClick={() => setZoom(zoom - .5)}>−</button>
          <span aria-live="polite">{Math.round(zoom * 100)}%</span>
          <button aria-label="Zoom in" disabled={zoom === 3} onClick={() => setZoom(zoom + .5)}>+</button>
          <button onClick={() => setZoom(1)}>Fit page</button>
        </div>
        <div className="preview-scroll" tabIndex={0} aria-label="Scrollable original page">
          <svg style={{width: `${zoom * 100}%`}} viewBox={`0 0 ${preview.width} ${preview.height}`}
            role="img" aria-label={`Original page ${preview.page_number} with source regions`}>
            <image href={preview.image} width={preview.width} height={preview.height} />
            {preview.regions.map((region, i) => <rect key={i} data-role={region.role}
              x={region.box[0] * preview.width} y={region.box[1] * preview.height}
              width={region.box[2] * preview.width} height={region.box[3] * preview.height}
              vectorEffect="non-scaling-stroke"><title>{region.role === 'context' ? 'Context / heading' : 'Evidence region'}</title></rect>)}
          </svg>
        </div>
        <p className="muted">Local page image; zoom does not add detail beyond the rendered resolution.</p>
      </>}
      {preview?.kind === 'csv' && <>
        <p>Record {preview.record_number} · {source.original_filename || 'Original CSV'}</p>
        <p className="muted">This citation refers to the whole record. Fields below retain their original values.</p>
        <dl className="source-fields preview-record">{preview.headers.map((header, i) => <div key={i}>
          <dt>{header}</dt><dd>{preview.raw_values[i] === '' ? 'Empty in source' : preview.raw_values[i]}</dd>
        </div>)}</dl>
      </>}
    </section>}
  </div>;
}
