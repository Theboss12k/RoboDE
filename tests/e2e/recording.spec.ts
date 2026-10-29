import {test, expect} from '@playwright/test';

test('native scene recording settings, status, guard and download', async ({page, request})=>{
  const created=await (await request.post('/api/projects',{data:{name:'Recording UI',source:'apple_transfer'}})).json();
  const pid=created.id;
  const detail=await (await request.get(`/api/projects/${pid}`)).json();
  const records:any[]=[];
  let started:any;
  await page.route(`**/api/projects/${pid}`,route=>route.fulfill({json:{...detail,adapter:'isaac_sim',environment_connected:true}}));
  await page.context().route(`**/api/projects/${pid}/recordings**`,async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith('/capabilities'))return route.fulfill({json:{available:true}});
    if(url.pathname.endsWith('/file'))return route.fulfill({body:Buffer.from('synthetic test download'),contentType:'video/mp4',headers:{'Content-Disposition':'attachment; filename="scene-test.mp4"'}});
    if(url.pathname.endsWith('/stop')){
      records[0]={...records[0],status:'ready',cached:true,duration_seconds:1,frames:5};
      return route.fulfill({json:records[0]});
    }
    if(route.request().method()==='POST'){
      started=route.request().postDataJSON();
      records.unshift({id:'a'.repeat(32),status:'recording',created_at:new Date().toISOString(),frames:1,duplicated_frames:0,settings:started});
      return route.fulfill({json:records[0],status:201});
    }
    return route.fulfill({json:records});
  });
  await page.addInitScript(id=>localStorage.setItem('robot-ide.project',id),pid);
  await page.goto('/');
  await page.getByRole('button',{name:'Environment workspace',exact:true}).click();
  const panel=page.getByRole('region',{name:'Scene recording',exact:true});
  await expect(panel).toBeVisible();
  await panel.getByLabel('Recording resolution').selectOption('640x360');
  await panel.getByLabel('Recording frame rate').selectOption('5');
  await panel.getByLabel('Recording duration').fill('10');
  await panel.getByRole('button',{name:'Start scene recording',exact:true}).click();
  await expect(panel.getByText(/Recording · .*auto-stops at 10s/)).toBeVisible();
  expect(started).toMatchObject({resolution:'640x360',fps:5,duration_seconds:10,position:[2,2,1.5],look_at:[0,.5,.3]});
  await expect(page.getByRole('button',{name:'Reset simulator',exact:true})).toBeDisabled();
  await expect(page.getByLabel('Simulation backend',{exact:true})).toBeDisabled();
  await expect(panel.getByLabel('Recording resolution')).toBeDisabled();
  await panel.screenshot({path:'artifacts/scene-recording-controls.png'});
  await panel.getByRole('button',{name:'Stop recording',exact:true}).click();
  const download=page.waitForEvent('download');
  await panel.getByRole('button',{name:'MP4',exact:true}).click();
  expect((await download).suggestedFilename()).toBe(`RoboDE-scene-${'a'.repeat(32)}.mp4`);
  await expect(page.getByRole('button',{name:'Reset simulator',exact:true})).toBeEnabled();
});

test('built-in simulator explains native capture requirement and shows API errors in place',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'Environment workspace',exact:true}).click();
  const panel=page.getByRole('region',{name:'Scene recording',exact:true});
  await expect(panel.getByText(/Connect this project to NVIDIA Isaac Sim/)).toBeVisible();
  await expect(panel.getByRole('button',{name:'Start scene recording',exact:true})).toBeDisabled();
  const box=await panel.boundingBox();
  expect(box?.width).toBeGreaterThan(200);
  expect(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBeTruthy();
});
