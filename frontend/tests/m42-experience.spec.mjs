import { test, expect } from '@playwright/test';

test('selected materials survive refresh, revalidate and clear with a new conversation without posting', async ({page}) => {
  let available = true, posts = 0;
  const doc = {document_id:'d1',original_filename:'prices.csv',status:'ready',stage:'ready',error:null,warnings:[],parsing:null};
  await page.route('**/api/documents',r=>r.fulfill({json:available?[doc]:[]}));
  page.on('request',r=>{if(r.method()==='POST')posts++;});
  await page.goto('/');
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await page.getByRole('checkbox').check();
  await page.reload();
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await expect(page.getByRole('checkbox')).toBeChecked();
  available=false;
  await page.reload();
  await expect(page.getByRole('status').filter({hasText:'no longer ready or available'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Send message',exact:true})).toBeDisabled();
  available=true;
  await page.reload();
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await expect(page.getByRole('checkbox')).not.toBeChecked();
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'New conversation',exact:true}).click();
  await page.reload();
  await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
  await expect(page.getByRole('checkbox')).not.toBeChecked();
  expect(posts).toBe(0);
});

test('waiting shows elapsed time and quota uncertainty, then exposes original CSV fields without inferred units', async ({page}) => {
  let complete=false, posts=0;
  const created=Date.now()/1000-82;
  const body={conversation_id:'wait',request_id:'r',question:'Price 001?',document_ids:['d1']};
  const source={citation_id:'S1',document_id:'d1',evidence_id:'e1',original_filename:'prices.csv',locator:{kind:'csv',record_number:1},
    text:'Bestellnummer: 001\nListenpreis: 12,50\ngültig ab: 01.06.2026',
    headers:['Bestellnummer','Listenpreis','gültig ab','EAN'],raw_values:['001','12,50','01.06.2026','000123']};
  await page.addInitScript(value=>sessionStorage.setItem('siteco-current-chat',JSON.stringify(value)),
    {conversation:'wait',created:created*1000,turns:[{body,question_id:'q',names:['prices.csv']}]});
  await page.route('**/api/documents',r=>r.fulfill({json:[]}));
  await page.route('**/api/questions/q?*',r=>r.fulfill({json:{...body,question_id:'q',created_at:created,
    status:complete?'completed':'running',stage:complete?'completed':'waiting_rate_limit',error:null,
    answer:complete?{outcome:'answered',segments:[{text:'Price is 12,50.',citation_ids:['S1'],calculation_ids:[]}],
      citations:[source],gaps:[],warnings:[],unresolved:[],tool_results:[],context:{shown_evidence_count:1,omitted_evidence_count:0},validation:{rejected_segments:0}}:null}}));
  page.on('request',r=>{if(r.method()==='POST')posts++;});
  await page.goto('/');
  await expect(page.locator('.question-progress')).toContainText(/8\d s elapsed/);
  await expect(page.locator('.question-progress')).toContainText('no reliable completion estimate');
  complete=true;
  await expect(page.locator('.model-answer')).toBeVisible();
  await expect(page.locator('.question-progress')).toHaveCount(0);
  await page.getByText('S1 · prices.csv · Record 1',{exact:true}).click();
  await expect(page.locator('.source-fields')).toContainText('Bestellnummer');
  await expect(page.locator('.source-fields')).toContainText('001');
  await expect(page.locator('.source-fields')).toContainText('01.06.2026');
  await expect(page.locator('.source-fields')).not.toContainText('EUR');
  expect(posts).toBe(0);
});
