import {test,expect}from'@playwright/test';

test('signed-in user reveals, copies and hides the workspace code without showing it on login',async({page,context})=>{
  await page.goto('/login');
  await expect(page.getByText('hosted-browser-test-code',{exact:true})).toHaveCount(0);
  expect((await page.request.post('/api/workspace/access')).status()).toBe(401);
  await page.getByLabel('Workspace access code',{exact:true}).fill('hosted-browser-test-code');
  await page.getByRole('button',{name:'Open workspace',exact:true}).click();
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await page.getByRole('button',{name:'Open configuration',exact:true}).click();
  await page.getByRole('button',{name:'Workspace',exact:true}).click();
  await expect(page.getByLabel('Revealed workspace access code',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Show workspace access code',exact:true}).click();
  await expect(page.getByLabel('Revealed workspace access code',{exact:true})).toHaveValue('hosted-browser-test-code');
  await context.grantPermissions(['clipboard-read','clipboard-write']);
  await page.getByRole('button',{name:'Copy access code',exact:true}).click();
  expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe('hosted-browser-test-code');
  await expect(page.getByRole('region',{name:'Workspace access settings',exact:true}).getByRole('status')).toContainText('Workspace access code copied.');
  await page.screenshot({path:'artifacts/ui-overhaul/workspace-access.png'});
  await page.getByRole('button',{name:'Hide access code',exact:true}).click();
  await expect(page.getByLabel('Revealed workspace access code',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Show workspace access code',exact:true}).click();
  await page.getByRole('button',{name:'AI Models',exact:true}).click();
  await page.getByRole('button',{name:'Workspace',exact:true}).click();
  await expect(page.getByLabel('Revealed workspace access code',{exact:true})).toHaveCount(0);
  await page.clock.install();
  await page.getByRole('button',{name:'Show workspace access code',exact:true}).click();
  await expect(page.getByLabel('Revealed workspace access code',{exact:true})).toBeVisible();
  await page.clock.fastForward(61000);
  await expect(page.getByLabel('Revealed workspace access code',{exact:true})).toHaveCount(0);
});

for(const status of [404,405])test(`desktop local runtime (${status}) uses scoped native access and clipboard fallback selects the code`,async({page})=>{
  await page.request.post('/login',{form:{code:'hosted-browser-test-code'}});
  await page.addInitScript(()=>{
    (window as any).robotIdeDesktop={platform:'darwin',workspaceAccessCode:async()=>({access_code:'native-local-test-code'})};
    Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw Error('Clipboard denied');}},configurable:true});
  });
  await page.route('**/api/workspace/access',route=>route.fulfill({status,json:{detail:'Endpoint unavailable on private runtime'}}));
  await page.goto('/');await page.getByRole('button',{name:'Continue',exact:true}).click();
  await page.getByRole('button',{name:'Open configuration',exact:true}).click();
  await page.getByRole('button',{name:'Workspace',exact:true}).click();
  await page.getByRole('button',{name:'Show workspace access code',exact:true}).click();
  const field=page.getByLabel('Revealed workspace access code',{exact:true});
  await expect(field).toHaveValue('native-local-test-code');
  await page.getByRole('button',{name:'Copy access code',exact:true}).click();
  await expect(field).toBeFocused();
  expect(await field.evaluate((el:HTMLInputElement)=>el.selectionEnd!-el.selectionStart!)).toBe('native-local-test-code'.length);
  await expect(page.getByRole('region',{name:'Workspace access settings',exact:true}).getByRole('status')).toContainText('Copy unavailable');
});
