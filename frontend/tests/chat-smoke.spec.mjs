import { test, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';

test('empty Docker runtime: new PDF and CSV upload to cited answers', async ({page,request}) => {
  test.skip(!process.env.M28_PDF || !process.env.M28_CSV, 'Opt in with authorized PDF/CSV originals and an empty Docker runtime.');
  test.setTimeout(360000);
  const directory = process.env.M28_OUTPUT || '../tmp/m28-docker';
  await mkdir(directory,{recursive:true});
  const observations = [], results = [], errors = [];
  page.on('pageerror',e => errors.push(e.message));
  page.on('response',async response => {
    if (/\/api\/questions\/[^/?]+\?/.test(response.url()) && response.ok()) {
      const task = await response.json().catch(()=>null);
      if(task && observations.at(-1)?.stage !== task.stage)
        observations.push({time:Date.now(),question_id:task.question_id,stage:task.stage});
    }
  });
  try {
    expect(await (await request.get('/api/documents')).json()).toEqual([]);
    await page.goto('/');
    await expect(page.getByRole('heading',{name:'Start with your documents.'})).toBeVisible();
    await page.screenshot({path:directory+'/empty.png',fullPage:true});
    const checks = [
      {kind:'pdf',path:process.env.M28_PDF,question:'Welche Farbtemperatur, Anschlussleistung und welches Gewicht hat die Bestellnummer 0MD5307L1830?'},
      {kind:'csv',path:process.env.M28_CSV,question:'Welchen Listenpreis und welches Gültigkeitsdatum hat 51DB11EC11B1D?'}];
    for (const check of checks) {
      const started = Date.now();
      const upload = page.waitForResponse(r => r.url().endsWith('/api/documents') && r.request().method()==='POST');
      await page.getByLabel('Upload files',{exact:true}).setInputFiles(check.path);
      const uploaded = await upload;
      expect(uploaded.status()).toBe(202);
      const {document_id} = await uploaded.json();
      await expect.poll(async()=> (await (await request.get('/api/documents/'+document_id)).json()).status,
        {timeout:240000,intervals:[1000]}).toBe('ready');
      const readyAt = Date.now();
      if(await page.getByRole('button',{name:'Show sidebar',exact:true}).isVisible())
        await page.getByRole('button',{name:'Show sidebar',exact:true}).click();
      const material = page.locator('.document').filter({hasText:'#'+document_id.slice(0,8)});
      await material.getByRole('checkbox').check();
      await page.getByRole('button',{name:'Hide sidebar',exact:true}).click();
      await page.getByLabel('Message',{exact:true}).fill(check.question);
      const submitted = page.waitForResponse(r => r.url().endsWith('/api/questions') && r.request().method()==='POST');
      const questionAt = Date.now();
      await page.getByRole('button',{name:'Send message',exact:true}).click();
      const response = await submitted;
      expect(response.status()).toBe(202);
      const initial = await response.json();
      let task;
      await expect.poll(async()=> {
        task = await (await request.get('/api/questions/'+initial.question_id,
          {params:{conversation_id:initial.conversation_id}})).json();
        return task.status;
      }, {timeout:250000,intervals:[1000]}).toMatch(/completed|failed/);
      results.push({kind:check.kind,upload_to_ready_ms:readyAt-started,answer_ms:Date.now()-questionAt,task});
      expect(task.status, JSON.stringify(task.error)).toBe('completed');
      expect(['answered','partial']).toContain(task.answer.outcome);
      expect(task.answer.segments.length).toBeGreaterThan(0);
      expect(task.answer.citations.every(s=>s.document_id===document_id && s.locator.kind===check.kind)).toBe(true);
      await expect(page.locator('.model-answer')).toBeVisible();
      await page.locator('.answer-source summary').first().click();
      await expect(page.locator('.answer-source pre').first()).toBeVisible();
      await page.screenshot({path:directory+'/'+check.kind+'-answer.png',fullPage:true});
      if(check.kind==='csv') {
        const text = task.answer.segments.map(s=>s.text).join(' ');
        expect(text).toContain('183,20');
        expect(text).toContain('01.06.2026');
        expect(task.answer.citations[0].locator.record_number).toBe(1);
        await page.getByRole('button',{name:'Browse matching records',exact:true}).click();
        await expect(page.locator('.csv-results')).toContainText('Records 1–1 of 1');
      }
      await page.reload();
      await expect(page.locator('.model-answer')).toBeVisible();
      await page.getByRole('button',{name:'New conversation',exact:true}).click();
    }
    expect(errors).toEqual([]);
  } finally {
    await writeFile(directory+'/browser-results.json',JSON.stringify({results,observations,errors},null,2));
  }
});
