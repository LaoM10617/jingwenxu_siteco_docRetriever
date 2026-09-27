import { test, expect } from '@playwright/test';

test('chat freezes scope, polls, resolves citations and restores without resubmitting', async ({ page }) => {
  const doc = {document_id:'d1', original_filename:'prices.csv',status:'ready',stage:'ready',
    error:null,warnings:[],parsing:null};
  let posts = 0, reads = 0, body;
  await page.route('**/api/documents', r => r.fulfill({json:[doc]}));
  await page.route('**/api/questions', async r => {
    posts++; body = r.request().postDataJSON();
    await r.fulfill({status:202,json:{...body,question_id:'q1',status:'queued',stage:'queued'}});
  });
  await page.route('**/api/questions/q1?*', r => {
    reads++;
    const task = {...body,question_id:'q1',status:'running',stage:'waiting_rate_limit',answer:null,error:null};
    if(reads >= 2) Object.assign(task,{status:'completed',stage:'completed',answer:{
      outcome:'answered',segments:[{text:'Price is 12,50.',citation_ids:['S1'],calculation_ids:[]}],
      citations:[{citation_id:'S1',document_id:'d1',evidence_id:'e1',original_filename:'prices.csv',
        locator:{kind:'csv',record_number:1},text:'Listenpreis: 12,50'}],gaps:[],warnings:[],unresolved:[],
      tool_results:[],context:{shown_evidence_count:1,omitted_evidence_count:0},validation:{rejected_segments:0}}});
    return r.fulfill({json:task});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Hide sidebar',exact:true}).click();
  await page.getByLabel('Message',{exact:true}).fill('Price 001?');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await expect(page.locator('.chat-thread')).toContainText('Waiting for model quota');
  await expect(page.locator('.chat-thread')).toContainText('Price is 12,50.');
  await page.getByText('S1 · prices.csv · Record 1',{exact:true}).click();
  await expect(page.locator('.chat-thread')).toContainText('Listenpreis: 12,50');
  expect(body.document_ids).toEqual(['d1']);
  expect(Object.keys(body).sort()).toEqual(['conversation_id','document_ids','question','request_id']);
  await page.reload();
  await expect(page.locator('.chat-thread')).toContainText('Price is 12,50.');
  expect(posts).toBe(1);
  await page.getByRole('button',{name:'New conversation',exact:true}).click();
  await expect(page.locator('.chat-thread')).toHaveCount(0);
  await expect(page.getByLabel('Message',{exact:true})).toBeEmpty();
});

test('an ambiguous submission resends the same identity and timeout is an execution failure', async ({page}) => {
  const bodies=[];
  await page.route('**/api/documents',r=>r.fulfill({json:[{document_id:'d1',original_filename:'a.csv',status:'ready',stage:'ready',error:null,warnings:[],parsing:null}]}));
  await page.route('**/api/questions',async r=>{
    bodies.push(r.request().postDataJSON());
    if(bodies.length===1) return r.abort('failed');
    return r.fulfill({status:202,json:{...bodies[1],question_id:'q2',status:'failed',stage:'failed',answer:null,
      error:{code:'question_timeout',message:'The question deadline expired.'}}});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Hide sidebar',exact:true}).click();
  await page.getByLabel('Message',{exact:true}).fill('001?');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await page.getByRole('button',{name:'Check / resend same request',exact:true}).click();
  await expect(page.locator('.chat-thread')).toContainText('Question failed (question_timeout)');
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toEqual(bodies[0]);
  await expect(page.locator('.chat-thread')).not.toContainText('Not enough evidence');
});

test('partial answer preserves scope limitations, warnings and duplicate paginated sources',async({page})=>{
  let body;
  await page.route('**/api/documents',r=>r.fulfill({json:[{document_id:'d1',original_filename:'a.csv',status:'ready',stage:'ready',error:null,warnings:[],parsing:null}]}));
  const source=n=>({document_id:'d1',evidence_id:'e'+n,original_filename:'a.csv',text:'Original 001 price 12,50',locator:{kind:'csv',record_number:n}});
  await page.route('**/api/questions',async r=>{
    body=r.request().postDataJSON();
    return r.fulfill({status:202,json:{...body,question_id:'q3',status:'completed',stage:'completed',error:null,
      answer:{outcome:'partial',segments:[{text:'Verified value.',citation_ids:['S1'],calculation_ids:[]}],
        citations:[{...source(1),citation_id:'S1'}],gaps:['The remaining records were not summarized.'],
        warnings:[{code:'missing_price',message:'One source price is missing.'}],unresolved:[],
        context:{shown_evidence_count:1,omitted_evidence_count:2},validation:{rejected_segments:1},
        tool_results:[{tool:'lookup_orders',document_ids:['d1'],result:{total:21,has_more:true}}]}}});
  });
  await page.route('**/api/questions/q3/csv/0?*',r=>{
    const offset=Number(new URL(r.request().url()).searchParams.get('offset'));
    return r.fulfill({json:{records:offset?[source(21)]:[source(1),source(2)],offset,limit:20,total:21,has_more:offset===0}});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Hide sidebar',exact:true}).click();
  await page.getByLabel('Message',{exact:true}).fill('001?');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Partial answer',exact:true})).toBeVisible();
  await expect(page.locator('.chat-thread')).toContainText('2 retrieved passages were not included');
  await expect(page.locator('.chat-thread')).toContainText('Some answer passages were withheld');
  await page.getByText('1 source warnings',{exact:true}).click();
  await expect(page.locator('.chat-thread')).toContainText('One source price is missing.');
  await page.getByRole('button',{name:'Browse matching records',exact:true}).click();
  await expect(page.locator('.csv-results .answer-source')).toHaveCount(2);
  await page.getByRole('button',{name:'Next records',exact:true}).click();
  await expect(page.locator('.csv-results')).toContainText('Records 21–21 of 21');
  await expect(page.locator('.model-answer')).toContainText('Verified value.');
});

test('changing selected materials while a question runs preserves its scope and sources', async ({page}) => {
  const docs = [
    {document_id:'pdf-a',original_filename:'same.pdf'},
    {document_id:'pdf-b',original_filename:'same.pdf'},
    {document_id:'csv-a',original_filename:'prices.csv'},
    {document_id:'csv-b',original_filename:'prices.csv'},
    {document_id:'pending',original_filename:'pending.pdf',status:'processing'},
  ].map(d=>({status:'ready',stage:'ready',error:null,warnings:[],parsing:null,...d}));
  const bodies = [];
  let complete = false;
  await page.route('**/api/documents',r=>r.fulfill({json:docs}));
  await page.route('**/api/questions',async r=>{
    const body=r.request().postDataJSON(); bodies.push(body);
    return r.fulfill({status:202,json:{...body,question_id:'q'+bodies.length,status:'queued',stage:'queued'}});
  });
  await page.route(/\/api\/questions\/q\d+\?/,r=>{
    const n=Number(new URL(r.request().url()).pathname.match(/q(\d+)$/)[1]);
    const body=bodies[n-1];
    const answer={outcome:'answered',segments:[{text:'Scoped answer '+n,citation_ids:['S1'],calculation_ids:[]}],
      citations:[{citation_id:'S1',document_id:body.document_ids[0],evidence_id:'e1',
        original_filename:'same.pdf',locator:{kind:'pdf',page_number:1},text:'Original scoped evidence'}],
      gaps:[],warnings:[],unresolved:[],tool_results:[],context:{shown_evidence_count:1,omitted_evidence_count:0},
      validation:{rejected_segments:0}};
    return r.fulfill({json:{...body,question_id:'q'+n,status:complete?'completed':'running',
      stage:complete?'completed':'retrieving',answer:complete?answer:null,error:null}});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  const boxes=page.getByRole('checkbox');
  await expect(boxes).toHaveCount(5);
  await expect(boxes.nth(4)).toBeDisabled();
  for(const i of [0,1,2,3]) await boxes.nth(i).check();
  await page.getByLabel('Message',{exact:true}).fill('First full scope');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await expect(page.locator('.chat-thread')).toContainText('Searching selected materials');
  for(const i of [0,2,3]) await boxes.nth(i).uncheck();
  expect(bodies[0].document_ids).toEqual(['pdf-a','pdf-b','csv-a','csv-b']);
  await expect(page.locator('.user-question')).toContainText('Materials: same.pdf, same.pdf, prices.csv, prices.csv');
  complete=true;
  await expect(page.locator('.chat-thread')).toContainText('Scoped answer 1');
  await page.locator('.answer-source summary').click();
  await expect(page.locator('.answer-source')).toContainText('Source #pdf-a');
  await page.getByLabel('Message',{exact:true}).fill('Second selected scope');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await expect(page.locator('.chat-thread')).toContainText('Scoped answer 2');
  expect(bodies[1].document_ids).toEqual(['pdf-b']);
  expect(bodies[1].conversation_id).toBe(bodies[0].conversation_id);
  expect(bodies[1].request_id).not.toBe(bodies[0].request_id);
  await page.reload();
  await expect(page.locator('.chat-turn')).toHaveCount(2);
  await expect(page.locator('.chat-turn').first()).toContainText('Materials: same.pdf, same.pdf, prices.csv, prices.csv');
  expect(bodies).toHaveLength(2);
});

for (const ambiguous of [false, true]) {
  test(`refresh during ${ambiguous ? 'ambiguous POST' : 'quota wait'} never automatically submits again`, async ({page}) => {
    const bodies=[];
    let stage='waiting_rate_limit', reads=0;
    await page.route('**/api/documents',r=>r.fulfill({json:[{document_id:'d1',original_filename:'a.csv',
      status:'ready',stage:'ready',error:null,warnings:[],parsing:null}]}));
    await page.route('**/api/questions',async r=>{
      bodies.push(r.request().postDataJSON());
      if(ambiguous && bodies.length===1) return r.abort('failed');
      return r.fulfill({status:202,json:{...bodies[0],question_id:'recover',status:'running',stage,
        answer:null,error:null}});
    });
    await page.route('**/api/questions/recover?*',r=>{
      reads++;
      return r.fulfill({json:{...bodies[0],question_id:'recover',status:'running',stage,answer:null,error:null}});
    });
    await page.goto('/');
    await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
    await page.getByRole('checkbox').check();
    await page.getByLabel('Message',{exact:true}).fill('001?');
    await page.getByRole('button',{name:'Send message',exact:true}).click();
    if(ambiguous) await expect(page.getByRole('button',{name:'Check / resend same request',exact:true})).toBeVisible();
    else await expect(page.locator('.chat-thread')).toContainText('Waiting for model quota');
    await page.reload();
    if(ambiguous) await expect(page.getByRole('button',{name:'Check / resend same request',exact:true})).toBeVisible();
    else await expect(page.locator('.chat-thread')).toContainText('Waiting for model quota');
    // Observe beyond the 1.5s poll interval: only status reads may repeat automatically.
    await page.waitForTimeout(1800);
    expect(bodies).toHaveLength(1);
    if(ambiguous) {
      expect(reads).toBe(0);
      await page.getByRole('button',{name:'Check / resend same request',exact:true}).click();
      await expect(page.locator('.chat-thread')).toContainText('Waiting for model quota');
      expect(bodies).toHaveLength(2);
      expect(bodies[1]).toEqual(bodies[0]);
    } else expect(reads).toBeGreaterThan(1);
    stage='retrieving';
    await expect(page.locator('.chat-thread')).toContainText('Searching selected materials');
    await expect(page.locator('.chat-thread')).not.toContainText('Waiting for model quota');
    expect(bodies).toHaveLength(ambiguous?2:1);
  });
}

for (const withPdfEvidence of [false, true]) {
  test(`CSV exact miss remains visible ${withPdfEvidence ? 'beside qualified PDF partial evidence' : 'without a fallback answer'}`, async ({page}) => {
    await page.route('**/api/documents',r=>r.fulfill({json:[
      {document_id:'pdf',original_filename:'products.pdf'},
      {document_id:'csv',original_filename:'prices.csv'}
    ].map(d=>({...d,status:'ready',stage:'ready',error:null,warnings:[],parsing:null}))}));
    const source={citation_id:'S1',document_id:'pdf',evidence_id:'e1',original_filename:'products.pdf',
      locator:{kind:'pdf',page_number:2},text:'A power: 20 W (at 25 C)',context:[{text:'Only product A at 25 C'}]};
    await page.route('**/api/questions',async r=>r.fulfill({status:202,json:{...r.request().postDataJSON(),
      question_id:'q-miss',status:'completed',stage:'completed',error:null,answer:{
        outcome:withPdfEvidence?'partial':'exact_not_found',
        segments:withPdfEvidence?[{text:'A power is 20 W at 25 C.',citation_ids:['S1'],calculation_ids:[]}]:[],
        citations:withPdfEvidence?[source]:[],gaps:withPdfEvidence?['The exact CSV price is unavailable.']:[],
        warnings:[],unresolved:[{code:'exact_not_found',order_ids:['001'],document_ids:['csv']}],
        context:{shown_evidence_count:withPdfEvidence?1:0,omitted_evidence_count:0},
        validation:{rejected_segments:0},tool_results:[{tool:'lookup_orders',document_ids:['csv'],
          result:{total:0,has_more:false}}]}}}));
    await page.goto('/');
    await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
    await page.getByRole('checkbox').nth(0).check();
    await page.getByRole('checkbox').nth(1).check();
    await page.getByLabel('Message',{exact:true}).fill('Power and price 001?');
    await page.getByRole('button',{name:'Send message',exact:true}).click();
    await expect(page.getByRole('heading',{name:withPdfEvidence?'Partial answer':'No exact match',exact:true})).toBeVisible();
    await expect(page.locator('.model-answer')).toContainText('No exact match: 001');
    await expect(page.locator('.model-answer')).toContainText('0 matching records');
    if(withPdfEvidence) {
      await page.getByText('S1 · products.pdf · Page 2',{exact:true}).click();
      await expect(page.locator('.answer-source')).toContainText('Only product A at 25 C');
      await expect(page.locator('.answer-source')).toContainText('A power: 20 W (at 25 C)');
      await expect(page.locator('.model-answer')).toContainText('The exact CSV price is unavailable.');
    } else await expect(page.locator('.answer-segment')).toHaveCount(0);
  });
}

for (const code of ['generation_authentication_failed','generation_rate_limited','generation_provider_unavailable',
                    'generation_invalid_output','question_timeout','question_interrupted','question_not_found']) {
  test(`restored ${code} stays distinct from insufficient evidence and is never resubmitted`, async ({page}) => {
    let posts=0;
    const body={conversation_id:'restore',request_id:'r',question:'001?',document_ids:['d1']};
    await page.addInitScript(body=>{
      if(!sessionStorage.getItem('siteco-current-chat')) sessionStorage.setItem('siteco-current-chat',JSON.stringify({
        conversation:body.conversation_id,created:Date.now(),turns:[{body,question_id:'failed',names:['prices.csv']}]}));
    },body);
    await page.route('**/api/documents',r=>r.fulfill({json:[{document_id:'d1',original_filename:'prices.csv',
      status:'ready',stage:'ready',error:null,warnings:[],parsing:null}]}));
    await page.route('**/api/questions',r=>{posts++; return r.abort();});
    await page.route('**/api/questions/failed?*',r=>code==='question_not_found'
      ? r.fulfill({status:404,json:{error:{code,message:'Question not found or expired.',retryable:false}}})
      : r.fulfill({json:{...body,question_id:'failed',status:'failed',stage:'failed',answer:null,
        error:{code,message:'Execution failed; submit a new question explicitly.',retryable:true}}}));
    await page.goto('/');
    const message=code==='question_not_found'?'Question not found or expired.':`Question failed (${code})`;
    await expect(page.locator('.chat-thread')).toContainText(message);
    await page.reload();
    await expect(page.locator('.chat-thread')).toContainText(message);
    await expect(page.locator('.model-answer')).toHaveCount(0);
    await expect(page.locator('.chat-thread')).not.toContainText('Not enough evidence');
    await expect(page.getByRole('button',{name:'Check / resend same request',exact:true})).toHaveCount(0);
    expect(posts).toBe(0);
  });
}

test('followup links completed parent after refresh and keeps current scope',async({page})=>{
  const bodies=[];
  const docs=['d1','d2'].map(document_id=>({document_id,original_filename:document_id+'.csv',status:'ready',stage:'ready',error:null,warnings:[],parsing:null}));
  const answer={outcome:'answered',segments:[{text:'Verified price.',citation_ids:[],calculation_ids:[]}],
    citations:[],gaps:[],warnings:[],unresolved:[],tool_results:[],context:{shown_evidence_count:0,omitted_evidence_count:0},validation:{rejected_segments:0}};
  const task=(body,i)=>({...body,question_id:'memory-'+i,status:'completed',stage:'completed',answer,error:null,
    conversation_expires_at:Date.now()/1000+86000});
  await page.route('**/api/documents',r=>r.fulfill({json:docs}));
  await page.route('**/api/questions',async r=>{
    bodies.push(r.request().postDataJSON());
    await r.fulfill({status:202,json:task(bodies.at(-1),bodies.length)});
  });
  await page.route('**/api/questions/memory-1?*',r=>r.fulfill({json:task(bodies[0],1)}));
  await page.goto('/');
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await page.getByRole('checkbox').nth(0).check();
  await page.getByLabel('Message',{exact:true}).fill('Price 001?');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await expect(page.locator('.chat-thread')).toContainText('Verified price.');
  await page.reload();
  await expect(page.locator('.chat-thread')).toContainText('Verified price.');
  expect(bodies).toHaveLength(1);
  if(await page.getByRole('button',{name:'Show sidebar',exact:true}).isVisible()) await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await page.getByRole('checkbox').nth(0).uncheck();
  await page.getByRole('checkbox').nth(1).check();
  await page.getByLabel('Message',{exact:true}).fill('And its price here?');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await expect.poll(()=>bodies.length).toBe(2);
  expect(bodies[1].previous_question_id).toBe('memory-1');
  expect(bodies[1].document_ids).toEqual(['d2']);
  expect(bodies[1].conversation_id).toBe(bodies[0].conversation_id);
});

test('expired memory is explicit and never silently submits a new conversation',async({page})=>{
  let posts=0;
  await page.addInitScript(()=>sessionStorage.setItem('siteco-current-chat',JSON.stringify({
    conversation:'expired-memory',created:Date.now()-86401000,turns:[]})));
  await page.route('**/api/documents',r=>r.fulfill({json:[]}));
  await page.route('**/api/questions',r=>{posts++;return r.abort();});
  await page.goto('/');
  await expect(page.getByText('Conversation memory expired. Start a new conversation.')).toBeVisible();
  await expect(page.getByRole('button',{name:'Send message',exact:true})).toBeDisabled();
  expect(posts).toBe(0);
});

test('ambiguous followup restores and manually retries the frozen parent only',async({page})=>{
  let posts=0;
  const bodies=[];
  const saved={conversation:'chain',created:Date.now(),turns:[
    {body:{conversation_id:'chain',request_id:'first',question:'001?',document_ids:['d1']},question_id:'parent',names:['a.csv']},
    {body:{conversation_id:'chain',request_id:'second',question:'Its price?',document_ids:['d1'],previous_question_id:'parent'},names:['a.csv']}
  ]};
  await page.addInitScript(value=>sessionStorage.setItem('siteco-current-chat',JSON.stringify(value)),saved);
  await page.route('**/api/documents',r=>r.fulfill({json:[]}));
  await page.route('**/api/questions/parent?*',r=>r.fulfill({json:{...saved.turns[0].body,question_id:'parent',status:'completed',stage:'completed',answer:null,error:null}}));
  await page.route('**/api/questions',r=>{
    posts++;bodies.push(r.request().postDataJSON());
    return r.fulfill({status:202,json:{...bodies.at(-1),question_id:'child',status:'failed',stage:'failed',answer:null,error:{code:'generation_timeout',message:'Provider timed out.'}}});
  });
  await page.goto('/');
  await expect(page.getByRole('button',{name:'Check / resend same request',exact:true})).toBeVisible();
  expect(posts).toBe(0);
  await page.reload();
  await page.getByRole('button',{name:'Check / resend same request',exact:true}).click();
  await expect(page.locator('.chat-thread')).toContainText('Question failed (generation_timeout)');
  expect(posts).toBe(1);
  expect(bodies[0]).toEqual(saved.turns[1].body);
});
