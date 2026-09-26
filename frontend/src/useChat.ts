import { useEffect, useRef, useState } from 'react';
import { HttpError, request, type Evidence } from './api';

export type Source = Evidence & {citation_id?: string; document_id: string; evidence_id: string;
  original_filename?: string; context?: {text: string}[]};
export type Answer = {
  outcome: string; segments: {text: string; citation_ids: string[]; calculation_ids: string[]}[];
  citations: Source[]; gaps: string[]; warnings: {message: string; page_number?: number; code: string}[];
  unresolved: {code: string; order_ids?: string[]}[];
  context: {shown_evidence_count: number; omitted_evidence_count: number};
  tool_results: {tool: string; document_ids: string[]; result: {total?: number; has_more?: boolean}}[];
  validation: {rejected_segments: number};
};
type Submission = {conversation_id: string; request_id: string; question: string; document_ids: string[]};
export type Task = Submission & {question_id: string; status: string; stage: string;
  answer: Answer | null; error: {code: string; message: string} | null};
export type Turn = {body: Submission; question_id?: string; task?: Task; error?: string;
  unavailable?: boolean; names: string[]};
type Chat = {conversation: string; created: number; turns: Turn[]};
const key = 'siteco-current-chat';
const fresh = (): Chat => ({conversation: crypto.randomUUID(), created: Date.now(), turns: []});
const finished = (task?: Task) => task?.status === 'completed' || task?.status === 'failed';

function restore(): Chat {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (saved && typeof saved.conversation === 'string' && saved.created > Date.now() - 86400000
        && Array.isArray(saved.turns) && saved.turns.length <= 50 && saved.turns.every((t: Turn) =>
          t.body?.conversation_id === saved.conversation && typeof t.body.question === 'string'
          && typeof t.body.request_id === 'string' && Array.isArray(t.body.document_ids)
          && Array.isArray(t.names))) {
      return {...saved, turns: saved.turns.map((t: Turn) => ({...t,
        error: t.question_id ? undefined : 'Submission was interrupted. Check the same request to recover it.'}))};
    }
  } catch { /* Unavailable browser storage does not prevent chat. */ }
  return fresh();
}

export function useChat() {
  const [chat, setChat] = useState<Chat>(restore);
  const [message, setMessage] = useState('');
  const current = useRef(chat.conversation);
  const submitting = useRef(new Set<string>());
  const [pollAgain, setPollAgain] = useState(0);
  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify({...chat, turns: chat.turns.map(({body, question_id, names}) =>
        ({body, question_id, names}))}));
    } catch { /* The current page still works without persistence. */ }
  }, [chat]);
  const pending = chat.turns.filter(t => t.question_id && !finished(t.task) && !t.unavailable);
  const pendingIds = pending.map(t => t.question_id).join(',');
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      for (const id of pendingIds.split(',').filter(Boolean)) {
        try {
          const task = await request<Task>(`/questions/${id}?conversation_id=${encodeURIComponent(chat.conversation)}`,
            {signal: controller.signal});
          if (controller.signal.aborted) return;
          setChat(c => c.conversation !== task.conversation_id ? c : {...c,
            turns: c.turns.map(t => t.question_id === id ? {...t, task, error: undefined} : t)});
        } catch (error) {
          if (controller.signal.aborted) return;
          setChat(c => c.conversation !== chat.conversation ? c : {...c, turns: c.turns.map(t =>
            t.question_id === id ? {...t, error: error instanceof Error ? error.message : 'Cannot read question status.',
              unavailable: error instanceof HttpError && error.status === 404} : t)});
        }
      }
      if (!controller.signal.aborted && pendingIds) timer = setTimeout(poll, 1500);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [chat.conversation, pendingIds, pollAgain]);

  async function submit(turn: Turn) {
    if (submitting.current.has(turn.body.request_id)) return;
    submitting.current.add(turn.body.request_id);
    setChat(c => ({...c, turns: c.turns.map(t => t.body.request_id === turn.body.request_id ? {...t, error: undefined} : t)}));
    try {
      const task = await request<Task>('/questions', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(turn.body), signal: AbortSignal.timeout(15000)});
      if (current.current === task.conversation_id) setChat(c => ({...c, turns: c.turns.map(t =>
        t.body.request_id === turn.body.request_id ? {...t, question_id: task.question_id, task, error: undefined} : t)}));
    } catch (error) {
      if (current.current === turn.body.conversation_id) setChat(c => ({...c, turns: c.turns.map(t =>
        t.body.request_id === turn.body.request_id ? {...t, error: error instanceof Error ? error.message : 'Submission failed.'} : t)}));
    } finally { submitting.current.delete(turn.body.request_id); }
  }
  const busy = chat.turns.some(t => !finished(t.task) && !t.error && !t.unavailable);
  function send(document_ids: string[], names: string[]) {
    if (busy || submitting.current.size || !message.trim() || !document_ids.length || chat.turns.length >= 50) return;
    const turn: Turn = {body: {conversation_id: chat.conversation, request_id: crypto.randomUUID(),
      question: message.trim(), document_ids: [...document_ids]}, names: [...names]};
    setChat(c => ({...c, turns: [...c.turns, turn]}));
    setMessage('');
    void submit(turn);
  }
  function newConversation() {
    const next = fresh(); current.current = next.conversation; setChat(next); setMessage('');
  }
  return {chat, message, setMessage, busy, send, newConversation, submit,
    refresh: () => setPollAgain(n => n + 1)};
}
