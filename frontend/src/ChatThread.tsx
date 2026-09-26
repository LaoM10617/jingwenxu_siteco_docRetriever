import { useState } from 'react';
import { request } from './api';
import type { Source, Turn } from './useChat';

const stages: Record<string, string> = {queued:'Question queued',planning:'Preparing question',
  retrieving:'Searching selected materials',querying_csv:'Looking up exact order numbers',
  waiting_rate_limit:'Waiting for model quota',generating:'Writing answer',calculating:'Checking numbers',
  validating:'Checking sources'};
const outcomes: Record<string, string> = {answered:'Answer',partial:'Partial answer',
  needs_clarification:'Please clarify your question',insufficient_evidence:'Not enough evidence',
  exact_not_found:'No exact match'};

function SourceView({source}: {source: Source}) {
  const location = source.locator.kind === 'csv' ? `Record ${source.locator.record_number}` : `Page ${source.locator.page_number}`;
  return <details className="answer-source"><summary>{source.citation_id ? `${source.citation_id} · ` : ''}
    {source.original_filename || source.document_id.slice(0,8)} · {location}</summary>
    <p className="muted">Source #{source.document_id.slice(0,8)}</p>
    {source.context?.map((c,i) => <p key={i} className="source-context">{c.text}</p>)}
    <pre>{source.text}</pre>
    {source.price_status && <p className="muted">Price status: {source.price_status}. Original values retained.</p>}
  </details>;
}

function CsvPages({turn,index}: {turn: Turn; index: number}) {
  const [page,setPage] = useState<{records: Source[];offset:number;limit:number;total:number;has_more:boolean} | null>(null);
  const [error,setError] = useState('');
  const [loading,setLoading] = useState(false);
  async function load(offset: number) {
    setLoading(true); setError('');
    try {
      setPage(await request(`/questions/${turn.question_id}/csv/${index}?conversation_id=${encodeURIComponent(turn.body.conversation_id)}&offset=${offset}&limit=20`));
    } catch (e) { setError(e instanceof Error ? e.message : 'Cannot load records.'); }
    finally { setLoading(false); }
  }
  return <div className="csv-results">
    <button disabled={loading} onClick={() => void load(0)}>Browse matching records</button>
    <p className="muted">Browsing more records does not extend or regenerate this answer.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {page && <><p>Records {page.total ? page.offset+1 : 0}–{page.offset+page.records.length} of {page.total}</p>
      {page.records.map(s => <SourceView key={`${s.document_id}:${s.evidence_id}`} source={s} />)}
      <button disabled={loading || page.offset===0} onClick={() => void load(Math.max(0,page.offset-page.limit))}>Previous records</button>{' '}
      <button disabled={loading || !page.has_more} onClick={() => void load(page.offset+page.limit)}>Next records</button>
    </>}
  </div>;
}

export default function ChatThread({turns,retry,refresh}: {turns:Turn[];retry:(t:Turn)=>Promise<void>;refresh:()=>void}) {
  return <section className="chat-thread" aria-label="Conversation">
    {turns.map(turn => {
      const task = turn.task, answer = task?.answer;
      return <article className="chat-turn" key={turn.body.request_id}>
        <div className="user-question"><h2>You</h2><p>{turn.body.question}</p>
          <p className="muted">Materials: {turn.names.join(', ')}</p></div>
        {turn.error && <div role="alert" className="notice"><p>{turn.error}</p>
          {!turn.question_id ? <button onClick={() => void retry(turn)}>Check / resend same request</button>
            : !turn.unavailable && <button onClick={refresh}>Check status now</button>}
        </div>}
        {!turn.error && (!task || ['queued','running'].includes(task.status)) &&
          <p role="status">{task ? stages[task.stage] || 'Processing question' : 'Submitting question…'}</p>}
        {task?.status === 'failed' && <div role="alert" className="error"><p>{task.error?.message}</p>
          <p>Question failed ({task.error?.code}). You can submit a new question.</p></div>}
        {answer && <div className="model-answer"><h2>{outcomes[answer.outcome] || answer.outcome}</h2>
          {answer.outcome === 'needs_clarification' && <p>Include explicit order numbers or clarify what you want to find in the selected materials.</p>}
          {answer.outcome === 'exact_not_found' && <p>No exact record matched the requested order numbers in this scope.</p>}
          {answer.outcome === 'insufficient_evidence' && <p>The retrieved evidence does not support an answer to this question.</p>}
          {answer.segments.map((segment,i) => <div className="answer-segment" key={i}>
            <p>{segment.text}</p>
            {segment.citation_ids.map(id => {
              const source = answer.citations.find(c => c.citation_id === id);
              return source ? <SourceView key={id} source={source} /> : null;
            })}
          </div>)}
          {answer.gaps.map((g,i) => <p className="answer-gap" key={i}>{g}</p>)}
          {answer.context.omitted_evidence_count > 0 && <p className="answer-gap">
            {answer.context.omitted_evidence_count} retrieved passages were not included in the answer context.</p>}
          {answer.validation.rejected_segments > 0 && <p className="answer-gap">Some answer passages were withheld because their sources could not be verified.</p>}
          {answer.unresolved.filter(u => u.code==='exact_not_found').map((u,i) => <p className="answer-gap" key={i}>No exact match: {u.order_ids?.join(', ')}</p>)}
          {answer.warnings.length > 0 && <details className="warnings"><summary>{answer.warnings.length} source warnings</summary>
            {answer.warnings.map((w,i) => <p key={i}>{w.page_number ? `Page ${w.page_number}: ` : ''}{w.message}</p>)}</details>}
          {answer.tool_results.map((tool,i) => tool.tool==='lookup_orders' ? <div key={i}>
            <p className="muted">{tool.result.total} matching records.{tool.result.has_more ? ' Only the first page was available for the answer.' : ''}</p>
            <CsvPages turn={turn} index={i} /></div> : null)}
          <p className="muted">Check the cited source and its conditions. Retrieval does not guarantee completeness.</p>
        </div>}
      </article>;
    })}
  </section>;
}
