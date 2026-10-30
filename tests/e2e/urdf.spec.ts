import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const sessions=new Set<string>();
test.beforeEach(async({page})=>{page.on('response',async response=>{if(response.request().method()==='POST'&&/\/library\/robots\/urdf_browser_[^/]+\/controls$/.test(response.url())&&response.ok())sessions.add((await response.json()).id);});});
test.afterEach(async({request})=>{for(const sid of sessions)await request.delete(`/api/controls/${sid}`);sessions.clear();});
const sample = resolve('SERVER_CLIENT/server/examples/robots/bench_gantry.urdf');
async function open(page: Page) {
  await page.goto('/');
  await page.getByRole('button', {name:'Open configuration',exact:true}).click();
  await page.getByText('Legacy robot definitions & adapters', {exact:true}).click();
  await page.getByRole('button', {name:'Add robot to library',exact:true}).click();
  await page.getByRole('button', {name:'Import URDF',exact:true}).click();
  await page.getByLabel('URDF source file',{exact:true}).setInputFiles(sample);
  await page.getByRole('button',{name:'Read URDF',exact:true}).click();
  await expect(page.getByRole('region',{name:'URDF robot review'})).toBeVisible();
}

test('URDF robot is reviewed, imported globally, controlled with IK and source retained',async({page,request})=>{
  test.setTimeout(90000);
  await open(page);
  const id='urdf_browser_'+Date.now();
  await page.getByLabel('URDF robot ID',{exact:true}).fill(id);
  await expect(page.getByLabel('URDF slide_x min',{exact:true})).toHaveAttribute('readonly','');
  await expect(page.getByLabel('URDF slide_x min',{exact:true})).toHaveValue('-0.5');
  await expect(page.getByRole('button',{name:'Save global robot & continue',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Validate robot definition',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('acceleration needs configuration');
  for(const joint of ['slide_x','slide_y','slide_z'])await page.getByLabel(`URDF ${joint} acceleration`,{exact:true}).fill('0.8');
  await page.getByRole('button',{name:'Validate robot definition',exact:true}).click();
  await expect(page.getByText('Definition validated · serial-chain IK available',{exact:true})).toBeVisible();
  await expect(page.getByText('Payload is unknown.',{exact:false})).toBeVisible();
  await expect.poll(async()=>((await (await request.get('/api/registry')).json()).some((m:any)=>m.robot.id===id))).toBe(false);
  await page.getByLabel('I reviewed the URDF robot configuration',{exact:true}).check();
  await page.screenshot({path:'artifacts/urdf-import-review.png'});
  await page.getByRole('button',{name:'Save global robot & continue',exact:true}).click();
  await expect(page.getByRole('heading',{name:'3. Control adapter for Bench gantry',exact:true})).toBeVisible();
  expect((await request.get(`/api/registry/${id}/source`)).status()).toBe(200);
  await page.getByRole('button',{name:'Continue to test',exact:true}).click();
  await page.getByRole('button',{name:'Connect controls',exact:true}).click();
  await page.getByText('Standardized task controls',{exact:true}).click();
  await page.getByLabel('Standard command type',{exact:true}).selectOption('MOVE_END_EFFECTOR');
  await page.getByLabel('Command X',{exact:true}).fill('.1');await page.getByLabel('Command Y',{exact:true}).fill('-.1');await page.getByLabel('Command Z',{exact:true}).fill('.35');
  await page.getByRole('button',{name:'Run standardized task',exact:true}).click();
  await expect(page.getByLabel('Feedback slide_y',{exact:true})).toContainText('0.1000');
  await page.screenshot({path:'artifacts/urdf-import-controls.png'});
  await page.getByRole('button',{name:'Disconnect controls',exact:true}).click();
  await page.getByRole('button',{name:'Finish · return to global library',exact:true}).click();
  const card=page.locator('.library-models article').filter({hasText:id});
  await expect(card.getByRole('link',{name:'Download URDF source',exact:true})).toBeVisible();
});

test('LLM suggestions require acceptance and cannot change extracted joint values',async({page,request})=>{
  const http=await import('node:http');
  const server=http.createServer(async(req,res)=>{
    for await(const _chunk of req) { /* consume provider request without logging internal instructions */ }
    res.writeHead(200,{'Content-Type':'application/json'});
    res.end(JSON.stringify({choices:[{message:{content:JSON.stringify({name:'Suggested gantry',description:'A three-axis kinematic preview.',tool_link:'tool_tip',notes:['Review the supplied acceleration values.']})}}]}));
  });
  await new Promise<void>(r=>server.listen(0,'127.0.0.1',r));
  const port=(server.address() as {port:number}).port;
  const before=await (await request.get('/api/llm/adapters')).json();
  const saved=await (await request.post('/api/llm/adapters',{data:{name:'URDF suggestions QA',base_url:`http://127.0.0.1:${port}/v1`,model:'test'}})).json();
  try{
    await open(page);
    await page.getByText('Optional LLM assistance',{exact:true}).click();
    await page.getByLabel('URDF LLM adapter',{exact:true}).selectOption(saved.id);
    await page.getByRole('button',{name:'Suggest robot metadata',exact:true}).click();
    await expect(page.getByLabel('LLM robot suggestions',{exact:true})).toContainText('Suggestions · not applied');
    await expect(page.getByLabel('URDF robot name',{exact:true})).toHaveValue('Bench gantry');
    await expect(page.getByLabel('URDF slide_x max',{exact:true})).toHaveValue('0.5');
    await page.getByRole('button',{name:'Use suggested metadata',exact:true}).click();
    await expect(page.getByLabel('URDF robot name',{exact:true})).toHaveValue('Suggested gantry');
    await expect(page.getByLabel('URDF slide_x acceleration',{exact:true})).toHaveValue('');
    await expect(page.locator('textarea[aria-label*="system prompt"]')).toHaveCount(0);
  }finally{
    await request.delete(`/api/llm/adapters/${saved.id}`);
    await request.put('/api/llm/default',{data:{adapter_id:before.default_id}});
    await new Promise<void>(r=>server.close(()=>r()));
  }
});

test('URDF review remains aligned on a compact desktop and blockers stay visible',async({page})=>{
  await page.setViewportSize({width:1100,height:760});await page.goto('/');
  await page.getByRole('button',{name:'Open configuration',exact:true}).click();
  await page.getByText('Legacy robot definitions & adapters', {exact:true}).click();
  await page.getByRole('button',{name:'Add robot to library',exact:true}).click();
  await page.getByRole('button',{name:'Import URDF',exact:true}).click();
  const source=(await readFile(sample,'utf8')).replace('type="prismatic"','type="floating"');
  await page.getByLabel('URDF source file',{exact:true}).setInputFiles({name:'unsupported.urdf',mimeType:'application/xml',buffer:Buffer.from(source)});
  await page.getByRole('button',{name:'Read URDF',exact:true}).click();
  await expect(page.locator('.urdf-blockers')).toContainText('floating joints are not supported');
  await expect(page.getByRole('button',{name:'Validate robot definition',exact:true})).toBeDisabled();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'artifacts/urdf-import-compact.png'});
  await page.locator('.configuration-modal').getByRole('button',{name:'Back',exact:true}).click();
  await expect(page.getByLabel('URDF source file',{exact:true})).toBeVisible();
});
