import {test,expect} from '@playwright/test';
for (const width of [1440,390]) test(`Settings lifecycle at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:1000});let n=1,calls=0;
 const state={revision:'r1',generation:{provider:'gemini',profiles:{gemini:{model:'gemini-test',credential_status:'configured',credential_source:'environment'},groq:{model:'groq-test',credential_status:'missing',credential_source:'none'}}},retrieval:{top_k:8,rerank_enabled:false},embedding:{model:'voyage-4',credential_status:'configured',credential_source:'environment',local_limits:{rpm:60,tpm:200000,min_interval:1,rerank_min_interval:1}}};
 await page.route('**/api/documents',r=>r.fulfill({json:[]}));
 await page.route('**/api/settings**',async r=>{
  if(r.request().method()==='GET')return r.fulfill({json:state});
  const b=r.request().postDataJSON();
  if(r.request().url().endsWith('/test')){calls++;return r.fulfill({json:{status:'failed',message:'Test failed: authentication_failed.',elapsed_seconds:.1,tested_revision:state.revision}});}
  if(r.request().method()==='PATCH'){
   expect(b.generation.profiles.gemini.credential.value).toBe('synthetic-key');state.retrieval=b.retrieval;state.generation.profiles.gemini.credential_source='override';
  }else if(b.mode==='credentials')state.generation.profiles.gemini.credential_status='disabled';
  else {state.generation.profiles.gemini.credential_status='configured';state.generation.profiles.gemini.credential_source='environment';}
  state.revision=`r${++n}`;return r.fulfill({json:state});
 });
 const open=async()=>{await page.getByRole('button',{name:'Show sidebar',exact:true}).click();await page.getByRole('button',{name:'Settings',exact:true}).click();};
 await page.goto('/');await open();expect(calls).toBe(0);
 await page.getByLabel('New Gemini API key').fill('synthetic-key');
 await page.getByLabel('Final Top K').fill('20');await page.getByLabel('Enable Voyage reranking').check();
 await expect(page.getByRole('button',{name:'Test inference & JSON'})).toBeDisabled();
 await page.getByRole('button',{name:'Apply settings',exact:true}).click();
 await expect(page.getByLabel('New Gemini API key')).toHaveValue('');
 await page.getByRole('button',{name:'Test inference & JSON'}).click();
 await expect(page.locator('.settings-panel').getByRole('status')).toContainText('authentication_failed');expect(calls).toBe(1);
 await page.reload();await open();await expect(page.getByLabel('Final Top K')).toHaveValue('20');
 await page.getByRole('button',{name:'Clear inference key',exact:true}).click();
 await expect(page.getByText('Key: disabled',{exact:false})).toBeVisible();
 await page.getByRole('button',{name:'Restore provider defaults',exact:true}).click();
 await expect(page.getByText('Key: configured (environment). Configured does not mean tested.',{exact:true})).toBeVisible();
 expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('synthetic-key');
 await page.screenshot({path:`../tmp/m45/settings-${width}.png`,fullPage:true});
});


