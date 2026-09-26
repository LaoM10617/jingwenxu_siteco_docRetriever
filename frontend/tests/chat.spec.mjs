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
