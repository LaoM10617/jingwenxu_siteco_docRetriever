import { useState } from 'react';
import SourcePreview from './SourcePreview';
import ResultArtifacts from './ResultArtifacts';
import type { Source, Turn } from './useChat';

function AnswerSources({sources}: {sources: Source[]}) {
  const unique = [...new Map(sources.map(source => [
    JSON.stringify([source.document_id, source.locator.kind,
      source.locator.kind === 'pdf' ? source.locator.page_number : source.evidence_id]), source,
  ])).values()];
  if (!unique.length) return null;
  if (unique.length === 1) return <SourcePreview source={unique[0]} />;
  return <details className="answer-source"><summary>Open original source</summary>
    {unique.map(source => <SourcePreview key={source.evidence_id} source={source}
      label={`${source.original_filename || 'Original source'} · ${source.locator.kind === 'pdf'
        ? `Page ${source.locator.page_number}` : `Record ${source.locator.record_number}`}`} />)}
  </details>;
}
function Controls({turn,control}:{turn:Turn;control:(t:Turn,a:'stop'|'resume',reply?:string)=>Promise<void>}) {
  const [reply,setReply] = useState('');
  const status = turn.task?.status;
  if (['queued','running'].includes(status || '')) return <button onClick={()=>void control(turn,'stop')}>Stop</button>;
  if (turn.task?.clarification) return <div>
    <p>{turn.task?.clarification}</p>
    <textarea aria-label="Clarification reply" value={reply} onChange={e=>setReply(e.target.value)} />
    <button disabled={!reply.trim()} onClick={()=>void control(turn,'resume',reply.trim())}>Continue</button>{' '}
    <button onClick={()=>void control(turn,'stop')}>Stop</button>
  </div>;
  if (['stopped','failed','recoverable'].includes(status || '')) return <button onClick={()=>void control(turn,'resume')}>Resume task</button>;
  return null;
}
export default function ChatThread({turns,retry,refresh,control}:{turns:Turn[];retry:(t:Turn)=>Promise<void>;
  refresh:()=>void;control:(t:Turn,a:'stop'|'resume',reply?:string)=>Promise<void>}) {
  return <section className="chat-thread" aria-label="Conversation">{turns.map(turn=> {
    const task=turn.task, answer=task?.answer ?? task?.partial_answer;
    const warnings = [...new Map((answer?.warnings ?? []).map(warning => [
      JSON.stringify(Object.entries(warning).sort(([a], [b]) => a.localeCompare(b))), warning,
    ])).values()];
    return <article className="chat-turn" key={turn.body.request_id}>
      <div className="user-question"><h2>You</h2><p>{turn.body.question}</p>
        {!!turn.names.length && <p className="muted">Materials: {turn.names.join(', ')}</p>}</div>
      {turn.error && <div role="alert"><p>{turn.error}</p><button onClick={()=>void retry(turn)}>Check / resend same request</button></div>}
      {!task && !turn.error && <p role="status">Submitting question…</p>}
      {task && task.status !== 'completed' && <p role="status">{{queued:'Question queued',running:'Working on your question',waiting:'Please clarify',
        stopped:'Task stopped',recoverable:'Task paused after restart. Resume when ready.',failed:'Task failed'}[task.status] || task.status}</p>}
      {task?.error && <p role="alert">{task.error.message}</p>}
      <Controls turn={turn} control={control}/>
      {answer && <div className="model-answer"><h2>{answer.outcome === 'answered' ? 'Answer' : answer.outcome}</h2>
        {!task?.answer && task?.partial_answer && <p role="status" className="answer-gap">Partial results only. The task has not finished; resume or answer the clarification to continue.</p>}
        {task?.source_available === false && <p role="status" className="answer-gap">Sources for this historical answer are no longer available in this session. It cannot be reused as current evidence.</p>}
        {answer.segments.map((segment,i)=><div key={i}><p>{segment.text}</p></div>)}
        {task?.source_available !== false && <AnswerSources sources={answer.citations.filter(source =>
          answer.segments.some(segment => segment.citation_ids.includes(source.citation_id ?? '')))} />}
        {answer.gaps.map((gap,i)=><p key={i} className="answer-gap">{gap}</p>)}
        {!!warnings.length && <details className="answer-warnings"><summary>See warnings</summary>
          {warnings.map((warning,i)=><p key={i}>{warning.page_number != null ? `Page ${warning.page_number} · ` : ''}{warning.message}</p>)}
        </details>}
        {task && <ResultArtifacts session={task.session_id} artifacts={task.artifacts ?? []}/>}
      </div>}
      {task?.status === 'recoverable' && <button onClick={refresh}>Refresh status</button>}
    </article>;
  })}</section>;
}
