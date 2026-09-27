import { useEffect, useState } from 'react';
import { request } from './api';

type Provider = 'gemini' | 'groq';
type Credential = {credential_status: string; credential_source: string};
type State = {revision: string; generation: {provider: Provider; profiles: Record<Provider, Credential & {model: string}>};
  retrieval: {top_k: number; rerank_enabled: boolean};
  embedding: Credential & {model: string; local_limits: {rpm: number; tpm: number; min_interval: number; rerank_min_interval: number}}};
type Probe = {status: string; message: string; code: string; elapsed_seconds: number; tested_revision: string};

export default function SettingsPanel() {
  const [state, setState] = useState<State | null>(null);
  const [provider, setProvider] = useState<Provider>('gemini');
  const [models, setModels] = useState<Record<Provider,string>>({gemini:'',groq:''});
  const [keys, setKeys] = useState({gemini:'',groq:'',voyage:''});
  const [topK, setTopK] = useState(8);
  const [rerank, setRerank] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const accept = (value: State) => {
    setState(value); setProvider(value.generation.provider);
    setModels({gemini:value.generation.profiles.gemini.model,groq:value.generation.profiles.groq.model});
    setTopK(value.retrieval.top_k); setRerank(value.retrieval.rerank_enabled);
    setKeys({gemini:'',groq:'',voyage:''}); setDirty(false);
  };
  const edit = () => {setDirty(true);setMessage('');setError('');};
  const load = async () => {
    setBusy(true); setError(''); setMessage('');
    try {accept(await request<State>('/settings'));}
    catch(e) {setError(e instanceof Error ? e.message : 'Cannot load Settings.');}
    finally {setBusy(false);}
  };
  useEffect(() => { void load(); }, []);
  const update = async (path: string, body: unknown, method='POST') => {
    setBusy(true);setError('');setMessage('');
    try {
      accept(await request<State>(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
      setMessage('Applied for new tasks. Connection has not been tested.');
    } catch(e) {setError(e instanceof Error ? e.message : 'Configuration was not applied. Reload to check its state.');}
    finally {setKeys({gemini:'',groq:'',voyage:''});setBusy(false);}
  };
  const apply = () => {
    if (!state) return;
    const profile = (p:Provider) => ({model:models[p], ...(keys[p] ? {credential:{action:'replace',value:keys[p]}} : {})});
    void update('/settings',{expected_revision:state.revision,
      generation:{provider,profiles:{gemini:profile('gemini'),groq:profile('groq')}},
      retrieval:{top_k:topK,rerank_enabled:rerank},
      ...(keys.voyage ? {embedding:{credential:{action:'replace',value:keys.voyage}}} : {})},'PATCH');
  };
  const clear = (scope:string, mode:string) => state && void update('/settings/clear',{expected_revision:state.revision,scope,mode});
  const test = async (target:string) => {
    if (!state) return;
    setBusy(true);setError('');setMessage('');
    try {
      const result = await request<Probe>('/settings/test',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({expected_revision:state.revision,target,explicit_probe:true})});
      // Re-read revision before attributing an asynchronous probe to current settings.
      const current = await request<State>('/settings');
      if (current.revision!==result.tested_revision) {
        accept(current); setMessage('Settings changed during the test. Its result does not verify the current configuration.');
      } else setMessage(`${target === 'generation' ? 'Inference' : 'Embedding'}: ${result.message} (${result.elapsed_seconds} s)`);
    } catch(e) {setError(e instanceof Error ? e.message : 'Test failed.');}
    finally {setBusy(false);}
  };
  return <section className="settings-panel" aria-label="Provider and retrieval settings">
    <h2>Settings</h2>
    <p className="muted">For this local instance. Keys stay in server memory. Refresh keeps applied settings; a backend restart restores server defaults.</p>
    <button onClick={() => void load()} disabled={busy}>Reload settings</button>
    {error && <p role="alert" className="error">{error}</p>}
    {message && <p role="status" className="notice">{message}</p>}
    {!state && <p>{busy ? 'Loading settings…' : 'Settings unavailable.'}</p>}
    {state && <fieldset disabled={busy}>
      <legend>Inference</legend>
      <label>Provider<select value={provider} onChange={e=>{setProvider(e.target.value as Provider);edit();}}>
        <option value="gemini">Gemini</option><option value="groq">Groq</option></select></label>
      <label>Model<input value={models[provider]} maxLength={200} onChange={e=>{setModels({...models,[provider]:e.target.value});edit();}} /></label>
      <p className="muted">Key: {state.generation.profiles[provider].credential_status} ({state.generation.profiles[provider].credential_source}). Configured does not mean tested.</p>
      <label>New {provider === 'gemini' ? 'Gemini' : 'Groq'} API key<input type="password" autoComplete="off" maxLength={4096} value={keys[provider]}
        placeholder="Leave blank to keep current key" onChange={e=>{setKeys({...keys,[provider]:e.target.value});edit();}} /></label>
      <div className="settings-actions"><button onClick={()=>clear(provider,'credentials')}>Clear inference key</button>
        <button onClick={()=>clear(provider,'defaults')}>Restore provider defaults</button></div>
      <hr /><h3>PDF retrieval</h3>
      <label>Final Top K<input type="number" min={1} max={20} step={1} value={topK} onChange={e=>{setTopK(Number(e.target.value));edit();}} /></label>
      <label className="settings-check"><input type="checkbox" checked={rerank} onChange={e=>{setRerank(e.target.checked);edit();}} />Enable Voyage reranking</label>
      <p className="muted">Up to 20 lexical + 20 vector candidates. The context budget may include fewer passages than Top K. Reranking sends candidate text to Voyage and may add charges.</p>
      <hr /><h3>Embedding</h3>
      <p>Voyage · {state.embedding.model} · 1024 dimensions</p>
      <p className="muted">Existing indexes stay unchanged. Key: {state.embedding.credential_status} ({state.embedding.credential_source}).</p>
      <label>New Voyage API key<input type="password" autoComplete="off" maxLength={4096} value={keys.voyage}
        placeholder="Used for embedding and reranking" onChange={e=>{setKeys({...keys,voyage:e.target.value});edit();}} /></label>
      <div className="settings-actions"><button onClick={()=>clear('voyage','credentials')}>Clear Voyage key</button>
        <button onClick={()=>clear('voyage','defaults')}>Restore Voyage default</button></div>
      <p className="muted">Local limits: {state.embedding.local_limits.rpm} RPM / {state.embedding.local_limits.tpm.toLocaleString()} TPM; {state.embedding.local_limits.min_interval} s minimum interval. Rerank interval: {state.embedding.local_limits.rerank_min_interval} s. These startup limits are not verified account quotas and also apply to replacement keys.</p>
      <hr />
      <button className="primary" disabled={!dirty || !Number.isInteger(topK) || topK<1 || topK>20 || !models[provider].trim()} onClick={apply}>Apply settings</button>
      <p className="muted">{dirty ? 'Unsaved changes. Apply before testing.' : 'Tests use the applied configuration.'} Each test sends fixed text to the selected provider and may incur a charge. No document content is sent.</p>
      <div className="settings-actions"><button disabled={dirty} onClick={()=>void test('generation')}>Test inference & JSON</button>
        <button disabled={dirty} onClick={()=>void test('embedding')}>Test embedding</button></div>
      <hr />
      <p className="muted">Clearing keys disables them for new tasks. Already accepted tasks retain their settings until they finish. Restoring defaults may re-enable server keys.</p>
      <div className="settings-actions"><button onClick={()=>clear('all','credentials')}>Clear all keys</button>
        <button onClick={()=>clear('all','defaults')}>Restore all defaults</button></div>
    </fieldset>}
  </section>;
}
