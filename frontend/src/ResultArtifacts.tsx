import { useEffect, useState } from 'react';
import { request } from './api';

type Rows = {columns:string[]; rows:(string|number|boolean|null)[][]; total:number; has_more:boolean; unit:string|null};
type Chart = {type:'bar'|'line'|'scatter'; x:string; y:string; title:string; table_artifact_id:string};
type Artifact = {artifact_id:string; kind:string};

function ResultTable({session,id}:{session:string; id:string}) {
  const [page,setPage] = useState<Rows|null>(null);
  const [offset,setOffset] = useState(0);
  const [error,setError] = useState('');
  useEffect(()=>{
    const abort = new AbortController();
    void request<Rows>(`/sessions/${session}/artifacts/${encodeURIComponent(id)}/rows?offset=${offset}&limit=100`,
      {signal:abort.signal}).then(value=>{setPage(value);setError('');}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});
    return ()=>abort.abort();
  },[session,id,offset]);
  if(error)return <p role="alert">{error}</p>;
  if(!page)return <p role="status">Loading result table…</p>;
  return <div><p>{page.total} result rows{page.unit ? ` · ${page.unit}` : ''}</p>
    <div style={{overflowX:'auto'}}><table><thead><tr>{page.columns.map(c=><th key={c}>{c}</th>)}</tr></thead>
      <tbody>{page.rows.map((row,i)=><tr key={offset+i}>{row.map((cell,j)=><td key={j}>{cell === null ? '—' : String(cell)}</td>)}</tr>)}</tbody></table></div>
    <button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-100))}>Previous rows</button>{' '}
    <button disabled={!page.has_more} onClick={()=>setOffset(offset+100)}>Next rows</button>
  </div>;
}

function ResultChart({session,id}:{session:string; id:string}) {
  const [value,setValue] = useState<{chart:Chart; table:Rows}|null>(null);
  const [error,setError] = useState('');
  useEffect(()=>{
    const abort = new AbortController();
    void (async()=>{
      const artifact = await request<{payload:Chart|null}>(`/sessions/${session}/artifacts/${encodeURIComponent(id)}`,{signal:abort.signal});
      if(!artifact.payload)throw new Error('This chart was removed with its source.');
      const chart = artifact.payload;
      const table = await request<Rows>(`/sessions/${session}/artifacts/${encodeURIComponent(chart.table_artifact_id)}/rows?limit=100`,{signal:abort.signal});
      setValue({chart,table});setError('');
    })().catch(e=>{if(!abort.signal.aborted)setError(e.message);});
    return ()=>abort.abort();
  },[session,id]);
  if(error)return <p role="alert">{error}</p>;
  if(!value)return <p role="status">Loading chart…</p>;
  const {chart,table} = value;
  const xIndex=table.columns.indexOf(chart.x), yIndex=table.columns.indexOf(chart.y);
  const rows=table.rows.filter(r=>r[yIndex] !== null && Number.isFinite(Number(r[yIndex])));
  const lo=Math.min(0,...rows.map(r=>Number(r[yIndex]))), hi=Math.max(0,...rows.map(r=>Number(r[yIndex])));
  const y=(n:number)=>210-(n-lo)/(hi-lo || 1)*180;
  const numericX=chart.type!=='bar' && rows.every(r=>r[xIndex] !== null && r[xIndex] !== '' && Number.isFinite(Number(r[xIndex])));
  const xmin=numericX?Math.min(...rows.map(r=>Number(r[xIndex]))):0;
  const xmax=numericX?Math.max(...rows.map(r=>Number(r[xIndex]))):0;
  const x=(row:(string|number|boolean|null)[],i:number)=>numericX?50+(Number(row[xIndex])-xmin)/(xmax-xmin||1)*500:50+(i+.5)*500/Math.max(1,rows.length);
  return <figure><figcaption>{chart.title} · {chart.x} / {chart.y}</figcaption>
    {table.has_more && <p>Chart preview shows the first 100 result rows. The complete result is in the table.</p>}
    <svg viewBox="0 0 600 250" role="img" aria-label={chart.title || `${chart.y} by ${chart.x}`} style={{maxWidth:800,width:'100%'}}>
      <line x1="45" x2="565" y1={y(0)} y2={y(0)} stroke="currentColor"/>
      <text x="0" y="25" fontSize="11">{hi}</text><text x="0" y="215" fontSize="11">{lo}</text>
      {chart.type==='line' && <polyline points={rows.map((r,i)=>`${x(r,i)},${y(Number(r[yIndex]))}`).join(' ')} fill="none" stroke="currentColor"/>}
      {rows.map((r,i)=><g key={i}>
        <title>{String(r[xIndex])}: {String(r[yIndex])}</title>
        {chart.type==='bar'?<rect x={x(r,i)-Math.max(1,350/rows.length)/2} y={Math.min(y(0),y(Number(r[yIndex])))}
          width={Math.max(1,350/rows.length)} height={Math.max(1,Math.abs(y(Number(r[yIndex]))-y(0)))} fill="currentColor"/>:
          <circle cx={x(r,i)} cy={y(Number(r[yIndex]))} r="3" fill="currentColor"/>}
        {rows.length<=10 && <text x={x(r,i)} y="235" textAnchor="middle" fontSize="10">{String(r[xIndex]).slice(0,24)}</text>}
      </g>)}
    </svg>
  </figure>;
}

export default function ResultArtifacts({session,artifacts}:{session:string; artifacts:Artifact[]}) {
  return <div>{artifacts.filter(a=>a.kind==='table'||a.kind==='chart').map(a=><details key={a.artifact_id} open>
    <summary>{a.kind==='table'?'Result table':'Chart'}</summary>
    {a.kind==='table'?<ResultTable session={session} id={a.artifact_id}/>:<ResultChart session={session} id={a.artifact_id}/>}
  </details>)}</div>;
}
