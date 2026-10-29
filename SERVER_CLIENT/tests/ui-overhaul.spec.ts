import {test,expect,type Page} from '@playwright/test';

async function open(page: Page) {
  await page.request.post('/login',{form:{code:'hosted-browser-test-code'}});
  await page.goto('/');
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.getByLabel('Select project',{exact:true})).toHaveValue('apple_transfer');
}

for(const viewport of [{width:1100,height:720},{width:1512,height:982},{width:1920,height:1080}]){
  test(`workspace alignment, selected states and utilities at ${viewport.width}px`,async({page})=>{
    await page.setViewportSize(viewport);await open(page);
    const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
    for(const workspace of ['Robots','Environment','Plans']){
      const nav=page.getByRole('button',{name:workspace+' workspace',exact:true});
      await nav.click();await expect(nav).toHaveAttribute('aria-current','page');
      await page.locator('.workspace-surface > *').first().evaluate(el=>Promise.allSettled(el.getAnimations().map(a=>a.finished)));
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      for(const name of ['Open configuration','Open tutorial','Toggle project explorer'])await expect(page.getByRole('button',{name,exact:true})).toBeInViewport();
      const bounds=await nav.boundingBox();expect(bounds!.height).toBeGreaterThanOrEqual(44);
      const activeBackground=await nav.evaluate(el=>getComputedStyle(el).backgroundColor);
      const other=page.getByRole('button',{name:(workspace==='Plans'?'Robots':'Plans')+' workspace',exact:true});
      expect(activeBackground).not.toBe(await other.evaluate(el=>getComputedStyle(el).backgroundColor));
      await page.screenshot({path:`artifacts/ui-overhaul/${viewport.width}-${workspace.toLowerCase()}.png`,animations:'disabled'});
    }
    await page.getByRole('button',{name:'Open configuration',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'Global configuration',exact:true});
    await expect(dialog).toBeInViewport();
    expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
    await dialog.getByRole('button',{name:'LLM adapters',exact:true}).click();
    await expect(dialog.getByRole('button',{name:'New LLM adapter',exact:true})).toBeVisible();
    await page.screenshot({path:`artifacts/ui-overhaul/${viewport.width}-configuration.png`,animations:'disabled'});
    await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Open configuration',exact:true})).toBeFocused();
    expect(errors).toEqual([]);
  });
}

test('dialog focus cycles, returns to opener and busy setup cannot close through the backdrop',async({page})=>{
  await open(page);
  const trigger=page.getByRole('button',{name:'Open configuration',exact:true});await trigger.click();
  const dialog=page.getByRole('dialog',{name:'Global configuration',exact:true});
  const close=dialog.getByRole('button',{name:'Close configuration',exact:true});
  await expect(close).toBeFocused();await page.keyboard.press('Shift+Tab');
  expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Tab');await expect(close).toBeFocused();
  await dialog.getByRole('button',{name:'Add robot to library',exact:true}).click();
  await dialog.getByRole('button',{name:'Import URDF',exact:true}).click();
  await page.getByLabel('URDF source file',{exact:true}).setInputFiles({name:'slow.urdf',mimeType:'application/xml',buffer:Buffer.from('<robot name="Slow"><link name="base"/></robot>')});
  let release!:()=>void;const gate=new Promise<void>(resolve=>release=resolve);
  await page.route('**/urdf/drafts?*',async route=>{await gate;await route.fulfill({status:422,json:{detail:'No controllable joints in this test model'}});});
  try{
    await page.getByRole('button',{name:'Read URDF',exact:true}).click();await expect(close).toBeDisabled();
    await page.locator('.modal-backdrop').click({position:{x:4,y:4}});
    await expect(dialog).toBeVisible();await page.keyboard.press('Escape');await expect(dialog).toBeVisible();
  }finally{release();}
  await expect(dialog.getByRole('alert')).toContainText('No controllable joints');
  await expect(close).toBeEnabled();await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.getByRole('button',{name:'New plan',exact:true}).first().click();
  const create=page.getByRole('dialog',{name:'New plan',exact:true});
  await expect(create.getByLabel('New plan name',{exact:true})).toBeFocused();
  await page.keyboard.press('Escape');await expect(create).toHaveCount(0);
  await expect(page.getByRole('button',{name:'New plan',exact:true}).first()).toBeFocused();
});
