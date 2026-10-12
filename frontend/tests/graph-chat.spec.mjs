import { test, expect } from '@playwright/test';

const answer = {outcome:'answered', segments:[{text:'Hello from the saved session.', citation_ids:[], calculation_ids:[]}],
  citations:[], gaps:[], warnings:[]};
const run = (status, extra={}) => ({run_id:'r1', request_id:'q1', session_id:'s1', question:'Hello',
  status, answer:null, error:null, ...extra});

async function mockGraph(page, initial=[]) {
  const state = {runs:initial, requests:[], created:0, legacy:0};
  await page.addInitScript(() => localStorage.setItem('siteco-graph-session','s1'));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    if (path.startsWith('/api/questions')) state.legacy++;
    if (path === '/api/documents') return route.fulfill({json:[]});
    if (path === '/api/sessions' && method === 'POST') {
      state.created++;
      return route.fulfill({status:201,json:{session_id:'s1',data_version:0,rule_version:0,sources:[]}});
    }
    if (path === '/api/sessions/s1') return route.fulfill({json:{session_id:'s1',data_version:0,rule_version:0,sources:[]}});
    if (path === '/api/sessions/s1/runs') {
      if (method === 'POST') {
        const body = request.postDataJSON();
        state.requests.push({path,body});
        state.runs = [run('completed',{request_id:body.request_id,question:body.question,answer})];
        return route.fulfill({status:202,json:state.runs[0]});
      }
      return route.fulfill({json:state.runs});
    }
    if (path === '/api/sessions/s1/runs/r1/resume' || path === '/api/sessions/s1/runs/r1/stop') {
      state.requests.push({path,body:request.postDataJSON()});
      state.runs = [run(path.endsWith('/stop') ? 'stopped' : 'completed',
        path.endsWith('/stop') ? {} : {answer})];
      return route.fulfill({status:path.endsWith('/stop') ? 200 : 202,json:state.runs[0]});
    }
    return route.fulfill({status:404,json:{error:{message:'Unexpected test endpoint: '+path}}});
  });
  return state;
}

test('saved session history reloads without resubmission and empty sources allow a greeting', async ({page}) => {
  const state = await mockGraph(page,[run('completed',{answer})]);
  await page.goto('/');
  await expect(page.locator('.model-answer')).toContainText('Hello from the saved session.');
  await page.reload();
  await expect(page.locator('.model-answer')).toContainText('Hello from the saved session.');
  expect(state.created).toBe(0);
  expect(state.requests).toHaveLength(0);
  await page.getByLabel('Message',{exact:true}).fill('Good morning');
  await expect(page.getByRole('button',{name:'Send message',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await expect.poll(()=>state.requests.length).toBe(1);
  expect(state.requests[0].path).toBe('/api/sessions/s1/runs');
  expect(state.requests[0].body).toMatchObject({question:'Good morning',explicit_sources:null,
    expected_data_version:0,expected_rule_version:0});
  expect(state.legacy).toBe(0);
});

test('clarification requires a reply and posts it to the same durable run', async ({page}) => {
  const state = await mockGraph(page,[run('waiting',{clarification:'Which product?'})]);
  await page.goto('/');
  await expect(page.getByText('Which product?',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Continue',exact:true})).toBeDisabled();
  await page.getByLabel('Clarification reply').fill('Product A');
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.locator('.model-answer')).toBeVisible();
  expect(state.requests).toEqual([{path:'/api/sessions/s1/runs/r1/resume',body:{reply:'Product A'}}]);
  expect(state.legacy).toBe(0);
});

test('running work can be stopped and resumed explicitly', async ({page}) => {
  const state = await mockGraph(page,[run('running')]);
  await page.goto('/');
  await page.getByRole('button',{name:'Stop',exact:true}).click();
  await expect(page.getByText('Task stopped',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Resume task',exact:true}).click();
  await expect(page.locator('.model-answer')).toBeVisible();
  expect(state.requests).toEqual([
    {path:'/api/sessions/s1/runs/r1/stop',body:{}},
    {path:'/api/sessions/s1/runs/r1/resume',body:{}}
  ]);
  expect(state.legacy).toBe(0);
});

test('recoverable work remains paused after page reload until resume is clicked', async ({page}) => {
  const state = await mockGraph(page,[run('recoverable')]);
  await page.goto('/');
  await expect(page.getByRole('button',{name:'Resume task',exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button',{name:'Resume task',exact:true})).toBeVisible();
  expect(state.requests).toHaveLength(0);
  await page.getByRole('button',{name:'Resume task',exact:true}).click();
  await expect(page.locator('.model-answer')).toBeVisible();
  expect(state.requests[0]).toEqual({path:'/api/sessions/s1/runs/r1/resume',body:{}});
});

test('unavailable historical sources show a warning while retaining the answer', async ({page}) => {
  await mockGraph(page,[run('completed',{answer,source_available:false})]);
  await page.goto('/');
  await expect(page.locator('.model-answer')).toContainText('Hello from the saved session.');
  await expect(page.getByText('Sources for this historical answer are no longer available in this session. It cannot be reused as current evidence.',{exact:true})).toBeVisible();
});

test('a stopped clarification still accepts its required reply on resume', async ({page}) => {
  const state = await mockGraph(page,[run('stopped',{clarification:'Which version should be used?'})]);
  await page.goto('/');
  await expect(page.getByText('Task stopped',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Clarification reply')).toBeVisible();
  await expect(page.getByRole('button',{name:'Continue',exact:true})).toBeDisabled();
  await page.getByLabel('Clarification reply').fill('The new version');
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.locator('.model-answer')).toBeVisible();
  expect(state.requests).toEqual([{path:'/api/sessions/s1/runs/r1/resume',body:{reply:'The new version'}}]);
});

test('CSV results paginate and numeric line charts preserve x spacing', async ({page}) => {
  await mockGraph(page,[run('completed',{answer,artifacts:[
    {artifact_id:'t1',kind:'table'},{artifact_id:'c1',kind:'chart'}]})]);
  await page.route('**/api/sessions/s1/artifacts/**', async route => {
    const url = new URL(route.request().url());
    if(url.pathname.endsWith('/c1')) return route.fulfill({json:{payload:{
      type:'line',x:'distance',y:'value',title:'Measured values',table_artifact_id:'t1'}}});
    const offset=Number(url.searchParams.get('offset') || 0);
    return route.fulfill({json:{columns:['distance','value'],
      rows:offset ? [[101,4]] : [[1,1],[2,2],[100,3]],total:101,has_more:offset===0,unit:null}});
  });
  await page.goto('/');
  await expect(page.getByText('101 result rows',{exact:true})).toBeVisible();
  await expect(page.getByRole('img',{name:'Measured values'})).toBeVisible();
  const points=await page.locator('polyline').getAttribute('points');
  const xs=points.split(' ').map(p=>Number(p.split(',')[0]));
  expect((xs[2]-xs[1])/(xs[1]-xs[0])).toBeCloseTo(98);
  await expect(page.getByText('Chart preview shows the first 100 result rows. The complete result is in the table.')).toBeVisible();
  await page.getByRole('button',{name:'Next rows',exact:true}).click();
  await expect(page.getByRole('cell',{name:'101',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Next rows',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Previous rows',exact:true}).click();
  await expect(page.getByRole('cell',{name:'100',exact:true})).toBeVisible();
});
