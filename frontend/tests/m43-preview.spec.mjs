import { test, expect } from '@playwright/test';

const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
async function sourcePage(page, kind='pdf') {
  const body={conversation_id:'preview',request_id:'r',question:'What is stated?',document_ids:['d1']};
  const source={citation_id:'S1',document_id:'d1',evidence_id:'e1',original_filename:kind==='pdf'?'terms.pdf':'prices.csv',
    locator:kind==='pdf'?{kind,page_number:2}:{kind,record_number:2},text:'Frozen source text'};
  await page.addInitScript(value=>sessionStorage.setItem('siteco-current-chat',JSON.stringify(value)),
    {conversation:'preview',created:Date.now(),turns:[{body,question_id:'q',names:[source.original_filename]}]});
  await page.route('**/api/documents',r=>r.fulfill({json:[]}));
  await page.route('**/api/questions/q?*',r=>r.fulfill({json:{...body,question_id:'q',status:'completed',stage:'completed',error:null,
    answer:{outcome:'answered',segments:[{text:'Answer',citation_ids:['S1'],calculation_ids:[]}],citations:[source],gaps:[],warnings:[],unresolved:[],
      tool_results:[],context:{omitted_evidence_count:0},validation:{rejected_segments:0}}}}));
  await page.goto('/');
  await page.locator('.answer-source > summary').click();
}

test('PDF citation opens original page and zooms evidence/context together without posting', async ({page}) => {
  let posts=0;
  page.on('request',r=>{if(r.method()==='POST')posts++;});
  await page.route('**/api/documents/d1/evidence/e1/preview',r=>r.fulfill({json:{kind:'pdf',page_number:2,width:200,height:300,image:png,
    notice:null,regions:[{role:'evidence',box:[.1,.2,.3,.1]},{role:'context',box:[.1,.1,.3,.05]}]}}));
  await sourcePage(page);
  await page.getByRole('button',{name:'Open original source',exact:true}).click();
  const preview=page.getByRole('region',{name:'Original source preview'});
  await expect(preview).toContainText('Page 2');
  const area=preview.locator('svg');
  const before=await area.boundingBox();
  const box=preview.locator('rect[data-role="evidence"]');
  const beforeBox=await box.boundingBox();
  await page.getByRole('button',{name:'Zoom in',exact:true}).click();
  const after=await area.boundingBox(),afterBox=await box.boundingBox();
  expect(after.width/before.width).toBeCloseTo(1.5,1);
  expect(afterBox.width/beforeBox.width).toBeCloseTo(1.5,1);
  await page.getByRole('button',{name:'Fit page',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(preview.locator('rect[data-role="context"]')).toHaveCount(1);
  expect(posts).toBe(0);
});

test('CSV preview labels every raw field and logical record without claiming field attribution', async ({page}) => {
  await page.route('**/api/documents/d1/evidence/e1/preview',r=>r.fulfill({json:{kind:'csv',record_number:2,
    headers:['Bestellnummer','Description','Listenpreis'],raw_values:['0002','Quoted; text\ncontinued','12,50']}}));
  await sourcePage(page,'csv');
  await page.getByRole('button',{name:'Open original source',exact:true}).click();
  const preview=page.getByRole('region',{name:'Original source preview'});
  await expect(preview).toContainText('Record 2');
  await expect(preview).toContainText('0002');
  await expect(preview).toContainText('Quoted; text');
  await expect(preview).toContainText('whole record');
});

test('unavailable old reference preserves frozen source text; missing coordinates show no boxes', async ({page}) => {
  let unavailable=true;
  await page.route('**/api/documents/d1/evidence/e1/preview',r=>unavailable
    ?r.fulfill({status:404,json:{error:{code:'evidence_not_found',message:'Unknown evidence ID.',retryable:false}}})
    :r.fulfill({json:{kind:'pdf',page_number:2,width:200,height:300,image:png,regions:[],notice:'Coordinates unavailable; original page only.'}}));
  await sourcePage(page);
  await page.getByRole('button',{name:'Open original source',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Unknown evidence');
  await expect(page.getByText('Frozen source text',{exact:true})).toBeVisible();
  unavailable=false;
  await page.getByRole('button',{name:'Retry preview',exact:true}).click();
  await expect(page.getByRole('region',{name:'Original source preview'})).toContainText('page only');
  await expect(page.locator('.source-preview rect')).toHaveCount(0);
  unavailable=true;
  await page.getByRole('button',{name:'Hide original source',exact:true}).click();
  await page.getByRole('button',{name:'Open original source',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Unknown evidence');
  await expect(page.locator('.source-preview svg')).toHaveCount(0);
});
