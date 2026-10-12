import { useEffect, useRef, useState } from 'react';
import { HttpError, request, type Evidence } from './api';

export type Source = Evidence & {citation_id?: string; document_id: string; evidence_id: string;
  original_filename?: string; context?: {text: string}[]};
export type Answer = {
  outcome: string; segments: {text: string; citation_ids: string[]; calculation_ids: string[]}[];
  citations: Source[]; gaps: string[]; warnings: {message: string; page_number?: number; code: string}[];
};
type Ref = {document_id: string; version_id: string};
type Session = {session_id: string; data_version: number; rule_version: number; sources: Ref[]};
type Submission = {request_id: string; question: string; expected_data_version: number;
  expected_rule_version: number; explicit_sources: Ref[] | null};
export type Task = {run_id: string; session_id: string; request_id: string; question: string; status: string;
  artifacts?: {artifact_id:string; kind:string}[];
  source_available?: boolean;
  clarification?: string | null; created_at?: number; answer: Answer | null;
  partial_answer?: Answer | null;
  error: {code: string; message: string} | null};
export type Turn = {body: Submission; question_id?: string; task?: Task; error?: string;
  session_id?: string;
  names: string[]; submittedAt?: number};
type Chat = {conversation: string; turns: Turn[]};
const key = 'siteco-graph-session';
const json = (body: unknown) => ({method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});

export function useChat() {
  const [chat, setChat] = useState<Chat>({conversation:'', turns:[]});
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [revision, refresh] = useState(0);
  const session = useRef<Promise<Session> | null>(null);
  const current = useRef('');
  async function ensureSession(): Promise<Session> {
    if (!session.current) session.current = (async () => {
      let sid: string | null = null;
      try { sid = localStorage.getItem(key); } catch { /* Browser storage is optional. */ }
      let value: Session;
      try { value = sid ? await request<Session>(`/sessions/${sid}`) : await request<Session>('/sessions', json({})); }
      catch (e) {
        if (!(e instanceof HttpError) || e.status !== 404) throw e;
        value = await request<Session>('/sessions', json({}));
      }
      current.current = value.session_id;
      try { localStorage.setItem(key, value.session_id); } catch { /* Server stores the conversation. */ }
      setChat({conversation:value.session_id, turns:[]});
      return value;
    })().catch(e => {session.current = null; throw e;});
    return session.current;
  }
  useEffect(() => { void ensureSession().catch(e => setError(e.message)); }, []);
  useEffect(() => {
    if (!chat.conversation) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const runs = await request<Task[]>(`/sessions/${chat.conversation}/runs`, {signal:controller.signal});
        if (controller.signal.aborted) return;
        setChat(c => c.conversation !== chat.conversation ? c : {...c, turns:[
          ...runs.map(task => {
            const prior = c.turns.find(t => t.body.request_id === task.request_id);
            return {...prior, session_id:task.session_id, body:prior?.body ?? {request_id:task.request_id, question:task.question,
              expected_data_version:0, expected_rule_version:0, explicit_sources:null},
              names:prior?.names ?? [], question_id:task.run_id, task, error:undefined};
          }), ...c.turns.filter(t => !runs.some(r => r.request_id === t.body.request_id))]});
        setError('');
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Cannot load conversation.'); }
      if (!controller.signal.aborted) timer = setTimeout(poll, 1500);
    }
    void poll();
    return () => {controller.abort(); clearTimeout(timer);};
  }, [chat.conversation, revision]);
  async function submit(turn: Turn) {
    try {
      const sid = turn.session_id ?? (await ensureSession()).session_id;
      await request(`/sessions/${sid}/runs`, json(turn.body));
      refresh(n => n+1);
    } catch (e) {
      setChat(c => ({...c, turns:c.turns.map(t => t.body.request_id === turn.body.request_id
        ? {...t,error:e instanceof Error ? e.message : 'Submission failed.'} : t)}));
    }
  }
  async function send(document_ids: string[], names: string[]) {
    if (sending || !message.trim()) return;
    setSending(true); setError('');
    const question = message.trim();
    try {
      const sid = (await ensureSession()).session_id;
      let state = await request<Session>(`/sessions/${sid}`);
      const refs: Ref[] = [];
      for (const id of document_ids) {
        const version = await request<Ref>(`/document-versions/${id}`);
        const source = {document_id:version.document_id,version_id:version.version_id};
        refs.push(source);
        if (!state.sources.some(s => s.version_id === id)) state = await request<Session>(`/sessions/${sid}/sources`,
          json({source,expected_data_version:state.data_version}));
      }
      const turn: Turn = {session_id:sid,body:{request_id:crypto.randomUUID(),question,
        expected_data_version:state.data_version,expected_rule_version:state.rule_version,
        explicit_sources:refs.length ? refs : null},names,submittedAt:Date.now()};
      setChat(c => c.conversation === sid ? {...c,turns:[...c.turns,turn]} : c);
      if (current.current === sid) setMessage('');
      await submit(turn);
    } catch (e) {setError(e instanceof Error ? e.message : 'Cannot submit question.');}
    finally {setSending(false);}
  }
  async function control(turn: Turn, action:'stop'|'resume', reply?:string) {
    try {
      await request(`/sessions/${chat.conversation}/runs/${turn.question_id}/${action}`, json(reply ? {reply} : {}));
      refresh(n => n+1);
    } catch (e) {setError(e instanceof Error ? e.message : 'Task action failed.');}
  }
  async function newConversation() {
    try {
      const value = await request<Session>('/sessions', json({}));
      session.current = Promise.resolve(value); current.current = value.session_id;
      try {localStorage.setItem(key,value.session_id);} catch { /* Optional pointer. */ }
      setChat({conversation:value.session_id,turns:[]}); setMessage(''); setError('');
    } catch (e) {setError(e instanceof Error ? e.message : 'Cannot create conversation.');}
  }
  const busy = sending || chat.turns.some(t => !t.error && (!t.task || ['queued','running','waiting'].includes(t.task.status)));
  return {chat,message,setMessage,busy,error,send,newConversation,submit,control,ensureSession,
    refresh:()=>refresh(n=>n+1)};
}
