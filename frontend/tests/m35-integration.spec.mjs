import {test,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';

// Explicit opt-in only: uses authorized D01/D06/D09 through the deployed browser/API.
test('M3 real authorized mixed scopes and conversational references',async({page,request})=>{
  test.skip(process.env.M35_REAL!=='1','Requires the authorized M3 runtime and D01 upload path.');
  test.setTimeout(600000);
  const output=process.env.M35_OUTPUT || '../tmp/m35';
  await mkdir(output,{recursive:true});
  const results=[],observations=[],errors=[];
  let posts=0;
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST' && r.url().endsWith('/api/questions'))posts++;});
  page.on('response',async r=>{
    if(/\/api\/questions\/[^/?]+\?/.test(r.url()) && r.ok()){
      const t=await r.json().catch(()=>null);
      if(t && observations.at(-1)?.stage!==t.stage) observations.push({time:Date.now(),id:t.question_id,stage:t.stage});
    }
  });
  async function select(ids){
    if(await page.getByRole('button',{name:'Show sidebar',exact:true}).isVisible())
      await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
    for(const box of await page.getByRole('checkbox').all()) if(await box.isChecked())await box.uncheck();
    for(const id of ids) await page.locator('.document').filter({hasText:'#'+id.slice(0,8)}).getByRole('checkbox').check();
    await page.getByRole('button',{name:'Hide sidebar',exact:true}).click();
  }
  async function ask(label,question,scope){
    await select(scope);
    await page.getByLabel('Message',{exact:true}).fill(question);
    const response=page.waitForResponse(r=>r.url().endsWith('/api/questions')&&r.request().method()==='POST');
    const started=Date.now();
    await page.getByRole('button',{name:'Send message',exact:true}).click();
    const submitted=await response;
    expect(submitted.status()).toBe(202);
    const initial=await submitted.json();
    let task;
    await expect.poll(async()=>{
      expect((await request.get('/api/health')).ok()).toBe(true);
      task=await (await request.get('/api/questions/'+initial.question_id,{params:{conversation_id:initial.conversation_id}})).json();
      return task.status;
    },{timeout:250000,intervals:[1000]}).toMatch(/completed|failed/);
    results.push({label,elapsed_ms:Date.now()-started,task});
    expect(task.status,JSON.stringify(task.error)).toBe('completed');
    await expect(page.locator('.chat-turn').last().locator('.model-answer')).toBeVisible();
    expect(task.answer.citations.every(s=>scope.includes(s.document_id))).toBe(true);
    const source=page.locator('.chat-turn').last().locator('.answer-source summary').first();
    if(await source.count())await source.click();
    await page.screenshot({path:output+'/'+label+'.png',fullPage:true});
    return task;
  }
  try{
    await page.goto('/');
    const docs=await(await request.get('/api/documents')).json();
    const pdf=docs.find(d=>d.document_id==='7758b95074074557b8bd2a4b72ef4237');
    const csv=docs.find(d=>d.document_id==='eeb7e731107d4759b3dd1d84f0c870ab');
    expect(pdf?.status).toBe('ready');expect(csv?.status).toBe('ready');
    let terms=docs.find(d=>d.original_filename==='Allgemeine_Einkaufsbedingungen_Siteco-Gruppe_April_2025.pdf'&&d.status==='ready');
    if(!terms){
      expect(process.env.M35_TERMS).toBeTruthy();
      const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/documents')&&r.request().method()==='POST');
      await page.getByLabel('Upload files',{exact:true}).setInputFiles(process.env.M35_TERMS);
      const response=await uploaded;expect(response.status()).toBe(202);terms=await response.json();
      await expect.poll(async()=>{
        expect((await request.get('/api/health')).ok()).toBe(true);
        expect((await(await request.get('/api/documents/'+pdf.document_id)).json()).status).toBe('ready');
        return(await(await request.get('/api/documents/'+terms.document_id)).json()).status;
      },{timeout:240000,intervals:[1000]}).toBe('ready');
    }
    const one=await ask('mixed-terms-price','Welche Incoterms-Fassung gilt laut Einkaufsbedingungen, und welchen Listenpreis hat die Bestellnummer 51DB11EC11B1D?',[terms.document_id,pdf.document_id,csv.document_id]);
    const text=t=>t.answer.segments.map(s=>s.text).join(' ');
    expect.soft(text(one)).toContain('2020');expect.soft(text(one)).toContain('183,20');
    expect.soft(new Set(one.answer.citations.map(s=>s.document_id))).toEqual(new Set([terms.document_id,csv.document_id]));
    await page.reload();await expect(page.locator('.model-answer')).toHaveCount(1);expect(posts).toBe(1);
    const two=await ask('csv-followup','Welches Gültigkeitsdatum hat die zuvor genannte Bestellnummer aus der Preisliste?',[csv.document_id]);
    expect(two.previous_question_id).toBe(one.question_id);
    expect.soft(text(two)).toContain('01.06.2026');
    expect.soft(two.answer.memory.references.map(r=>r.term)).toContain('51DB11EC11B1D');
    expect(two.answer.citations.every(s=>s.document_id===csv.document_id)).toBe(true);
    await page.getByRole('button',{name:'New conversation',exact:true}).click();
    const three=await ask('pdf-and-exact-miss','Nenne getrennt Farbtemperatur und Anschlussleistung für Rondel 0MD5307L1830 und 0MD5307L0940. Suche zusätzlich den exakten Listenpreis für 51DB11EC11B1D-NOT-FOUND in der CSV.',[pdf.document_id,csv.document_id]);
    expect.soft(three.answer.outcome).toBe('partial');
    expect.soft(three.answer.tool_results.find(t=>t.tool==='lookup_orders')?.result.total).toBe(0);
    expect.soft(three.answer.unresolved.some(u=>u.code==='exact_not_found')).toBe(true);
    expect.soft(text(three)).toContain('0MD5307L1830');expect.soft(text(three)).toContain('0MD5307L0940');
    const four=await ask('pdf-followup','Und welche Farbtemperatur und Anschlussleistung hat die zweite Leuchte?',[pdf.document_id]);
    expect(four.previous_question_id).toBe(three.question_id);
    expect.soft(four.answer.memory.references.map(r=>r.term)).toContain('0MD5307L0940');
    expect.soft(text(four)).toMatch(/4[. ]?000\s*K/);expect.soft(text(four)).toMatch(/9\s*W/);
    expect(four.answer.citations.every(s=>s.document_id===pdf.document_id&&s.locator.page_number===2)).toBe(true);
    await page.reload();await expect(page.locator('.model-answer')).toHaveCount(2);expect(posts).toBe(4);
    expect(errors).toEqual([]);
  }finally{await writeFile(output+'/real-results.json',JSON.stringify({results,observations,errors,posts},null,2));}
});

for(const label of ['csv-followup','pdf-followup'])test(`M3 real resolved subject regression: ${label}`,async({page,request})=>{
  test.skip(!process.env.M35_REPLAY_FILE,'Opt in only with a retained authorized failure report.');
  test.setTimeout(260000);
  const {readFile}=await import('node:fs/promises');
  const report=JSON.parse(await readFile(process.env.M35_REPLAY_FILE,'utf8'));
  const previous=report.results.find(r=>r.label===(label==='pdf-followup'?'pdf-and-exact-miss':'mixed-terms-price')).task;
  const original=report.results.find(r=>r.label===label).task;
  const body={conversation_id:previous.conversation_id,request_id:'restored-parent',question:previous.question,document_ids:previous.document_ids};
  await page.addInitScript(value=>{if(!sessionStorage.getItem('siteco-current-chat'))sessionStorage.setItem('siteco-current-chat',JSON.stringify(value));},{
    conversation:previous.conversation_id,created:previous.created_at*1000,expires:previous.conversation_expires_at*1000,
    turns:[{body,question_id:previous.question_id,names:['Authorized retained parent']}]});
  let posts=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/questions'))posts++;});
  await page.goto('/');await expect(page.locator('.model-answer')).toHaveCount(1);expect(posts).toBe(0);
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  for(const id of original.document_ids)await page.locator('.document').filter({hasText:'#'+id.slice(0,8)}).getByRole('checkbox').check();
  await page.getByRole('button',{name:'Hide sidebar',exact:true}).click();
  await page.getByLabel('Message',{exact:true}).fill(original.question);
  const response=page.waitForResponse(r=>r.url().endsWith('/api/questions')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  const initial=await(await response).json();let task;
  await expect.poll(async()=>{
    task=await(await request.get('/api/questions/'+initial.question_id,{params:{conversation_id:initial.conversation_id}})).json();
    return task.status;
  },{timeout:245000,intervals:[1000]}).toMatch(/completed|failed/);
  const output=process.env.M35_OUTPUT||'../tmp/m35/fix-validation';await mkdir(output,{recursive:true});
  await writeFile(output+'/'+label+'.json',JSON.stringify(task,null,2));
  expect(task.status,JSON.stringify(task.error)).toBe('completed');
  expect(task.previous_question_id).toBe(previous.question_id);
  const text=task.answer.segments.map(s=>s.text).join(' ');
  if(label==='pdf-followup'){
    expect(task.answer.memory.references.map(r=>r.term)).toContain('0MD5307L0940');
    expect(text).toContain('0MD5307L0940');expect(text).toMatch(/4[. ]?000\s*K/);expect(text).toMatch(/9\s*W/);
    expect(text).not.toContain('0MD5307L1830');
  }else expect(text).toContain('01.06.2026');
  expect(task.answer.citations.every(s=>original.document_ids.includes(s.document_id))).toBe(true);
  await expect(page.locator('.model-answer')).toHaveCount(2);
  await page.locator('.chat-turn').last().locator('.answer-source summary').first().click();
  await page.screenshot({path:output+'/'+label+'.png',fullPage:true});
  await page.reload();await expect(page.locator('.model-answer')).toHaveCount(2);expect(posts).toBe(1);
});

for(const label of ['csv-followup','pdf-followup'])test(`M3 restore retained real task pair without POST: ${label}`,async({page})=>{
  test.skip(!process.env.M35_RESTORE_DIR,'Requires retained successful authorized task results; no new model calls.');
  const {readFile}=await import('node:fs/promises');
  const report=JSON.parse(await readFile(process.env.M35_REPLAY_FILE,'utf8'));
  const parent=report.results.find(r=>r.label===(label==='pdf-followup'?'pdf-and-exact-miss':'mixed-terms-price')).task;
  const child=JSON.parse(await readFile(process.env.M35_RESTORE_DIR+'/'+label+'.json','utf8'));
  const turns=[parent,child].map(t=>({question_id:t.question_id,names:['Authorized materials'],body:{conversation_id:t.conversation_id,
    request_id:t.question_id,question:t.question,document_ids:t.document_ids,...(t.previous_question_id?{previous_question_id:t.previous_question_id}:{})}}));
  await page.addInitScript(value=>{if(!sessionStorage.getItem('siteco-current-chat'))sessionStorage.setItem('siteco-current-chat',JSON.stringify(value));},
    {conversation:parent.conversation_id,created:parent.created_at*1000,expires:parent.conversation_expires_at*1000,turns});
  let posts=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/questions'))posts++;});
  await page.goto('/');await expect(page.locator('.model-answer')).toHaveCount(2);
  await expect(page.locator('.chat-turn').last()).toContainText(label==='pdf-followup'?'0MD5307L0940':'01.06.2026');
  await page.reload();await expect(page.locator('.model-answer')).toHaveCount(2);expect(posts).toBe(0);
});
