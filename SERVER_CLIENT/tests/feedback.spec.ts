import { test, expect, type Page } from '@playwright/test';
async function open(page:Page) {
 await page.goto('/'); await page.getByLabel('Workspace access code').fill('hosted-browser-test-code');
 await page.getByRole('button',{name:'Open workspace',exact:true}).click();
 await expect(page.getByLabel('Select project',{exact:true})).toBeVisible();
}
async function visibleInFlow(page:Page, message:string) {
 const alert=page.getByRole('alert').filter({hasText:message});await expect(alert).toBeVisible();
 const rect=await alert.boundingBox();expect(rect).not.toBeNull();
 expect(rect!.y).toBeGreaterThanOrEqual(0);expect(rect!.y+rect!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
 expect(await alert.evaluate(el=>getComputedStyle(el).position)).toBe('static');
 return alert;
}
test('failed dialog submission remains visible inside the dialog without covering its controls',async({page})=>{
 await open(page);
 await page.route('**/plan-definitions',async route=>route.request().method()==='POST'?route.fulfill({status:422,json:{detail:'Please choose a different plan name.'}}):route.continue());
 await page.getByRole('button',{name:'New plan',exact:true}).first().click();
 const dialog=page.getByRole('dialog',{name:'New plan',exact:true});
 await dialog.getByLabel('New plan name').fill('Rejected name');
 await dialog.getByRole('button',{name:'Create plan',exact:true}).click();
 const alert=await visibleInFlow(page,'Please choose a different plan name.');
 expect(await alert.evaluate(el=>getComputedStyle(el).color)).toBe('rgb(255, 180, 173)');
 await expect(dialog.getByRole('alert')).toContainText('Please choose');
 const button=await dialog.getByRole('button',{name:'Create plan',exact:true}).boundingBox();const box=await alert.boundingBox();
 expect(box!.y).toBeGreaterThanOrEqual(button!.y+button!.height);
 await page.screenshot({path:'artifacts/qa-20261027/dialog-warning.png'});
 await alert.getByRole('button',{name:'Dismiss error'}).click();await expect(dialog.getByRole('alert')).toHaveCount(0);
});
test('GPU startup failures are polled and shown beside the clicked controls in a scrolled panel',async({page})=>{
 await open(page);
 await page.request.put('/api/configuration/isaac',{data:{deployment:'gcp',token:'qa-fake-worker-token',gcp_project:'qa-project',gcp_zone:'qa-zone',gcp_instance:'qa-vm',on_demand:true}});
 let starts=0;
 await page.route('**/configuration/isaac/gpu/start',async route=>{starts++;await route.fulfill({status:202,json:{status:'starting',message:'Starting GPU safely'}});});
 await page.route('**/configuration/isaac/gpu',route=>route.fulfill({json:{status:'error',message:'ZONE_RESOURCE_POOL_EXHAUSTED: No available L4 GPUs',configured:true}}));
 await page.reload();await page.getByRole('button',{name:'Environment workspace',exact:true}).click();
 await page.getByRole('button',{name:'Isaac Sim setup',exact:true}).click();
 const button=page.getByRole('button',{name:'Start GPU VM',exact:true});await button.scrollIntoViewIfNeeded();
 expect(starts).toBe(0);await button.click();
 const alert=await visibleInFlow(page,'GPU capacity is unavailable');
 const box=await alert.boundingBox();const control=await button.boundingBox();expect(box!.y).toBeGreaterThanOrEqual(control!.y+control!.height);
 await alert.getByText('Technical details',{exact:true}).click();await expect(alert.locator('pre')).toContainText('ZONE_RESOURCE_POOL_EXHAUSTED');
 await page.screenshot({path:'artifacts/qa-20261027/gpu-warning.png'});expect(starts).toBe(1);
});
test('workspace layout and NVIDIA labels stay aligned at laptop and desktop sizes',async({page})=>{
 await open(page);
 for(const width of [1280,1512,1920]) {
  await page.setViewportSize({width,height:900});
  for(const name of ['Robots','Environment','Plans']) {
   await page.getByRole('button',{name:name+' workspace',exact:true}).click();
   await page.locator('.workspace-surface > *').first().evaluate(el=>Promise.allSettled(el.getAnimations().map(a=>a.finished)));
   if(name==='Environment')await expect(page.locator('.environment-scene .scene-robot-label').first()).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   await page.screenshot({path:`artifacts/qa-20261027/ide-${name.toLowerCase()}-${width}.png`});
  }
 }
 await page.getByRole('button',{name:'Environment workspace',exact:true}).click();
 await page.getByRole('button',{name:'Isaac Sim setup',exact:true}).click();
 // Measure in one frame: the opening panel can reflow between two protocol calls.
 await expect.poll(()=>page.locator('.isaac-connection summary .nvidia-tool-heading').evaluate(label=>{
  const l=label.getBoundingClientRect(),m=label.querySelector('.nvidia-logo')!.getBoundingClientRect();
  return Math.abs(m.y+m.height/2-l.y-l.height/2);
 })).toBeLessThan(2);
 expect(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--ui-surface').trim())).toBe('#111722');
});

test('sign-in failure is clear and uses the same dark theme on a narrow screen',async({page})=>{
 await page.setViewportSize({width:320,height:720});await page.goto('/login');
 await page.getByLabel('Workspace access code').fill('wrong-workspace-code');
 await page.getByRole('button',{name:'Open workspace',exact:true}).click();
 await expect(page.getByRole('alert')).toHaveText('That code did not match. Please try again.');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(await page.locator('body').evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(8, 11, 16)');
 await page.screenshot({path:'artifacts/qa-20261027/login-warning-phone.png'});
});
