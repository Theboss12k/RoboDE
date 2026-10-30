import {test, expect} from '@playwright/test';

test('compact desktop navigation and configuration remain aligned and usable', async ({page}) => {
  await page.setViewportSize({width:1100, height:720});
  await page.request.post('/login', {form:{code:'hosted-browser-test-code'}});
  await page.goto('/', {waitUntil:'domcontentloaded'});
  await page.getByRole('button', {name:'Continue', exact:true}).click();
  for (const name of ['Robots', 'Environment', 'Plans']) {
    await page.getByRole('button', {name:`${name} workspace`, exact:true}).click();
    await page.locator('.workspace-surface > *').first().evaluate(el=>Promise.allSettled(el.getAnimations().map(a=>a.finished)));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole('button', {name:'Open configuration', exact:true})).toBeInViewport();
    await expect(page.getByRole('button', {name:'Open tutorial', exact:true})).toBeInViewport();
    await page.screenshot({path:`artifacts/ui-final/compact-${name.toLowerCase()}.png`});
  }
  await page.getByRole('button', {name:'Open configuration', exact:true}).click();
  const config = page.getByRole('dialog', {name:'Global configuration', exact:true});
  await expect(config).toBeVisible();
  await config.getByText('Legacy robot definitions & adapters',{exact:true}).click();
  await expect(config.getByRole('button', {name:'Add robot to library', exact:true})).toBeVisible();
  await expect(config.getByRole('button', {name:'Configure adapters & test', exact:true}).first()).toBeVisible();
  await page.screenshot({path:'artifacts/ui-final/configuration-library.png'});
  await config.getByRole('navigation', {name:'Global robot libraries', exact:true}).getByRole('button', {name:'Control adapters', exact:true}).click();
  await expect(config.getByRole('heading', {name:'Global control adapter library', exact:true})).toBeVisible();
  await config.getByRole('button', {name:'AI Models', exact:true}).click();
  await expect(config.getByRole('button', {name:'New AI connection', exact:true})).toBeVisible();
  await page.screenshot({path:'artifacts/ui-final/configuration-llm.png'});
  expect(await config.evaluate(el=>el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await config.getByRole('button', {name:'Close configuration', exact:true}).click();
  await expect(config).toHaveCount(0);
  await page.getByRole('button', {name:'Toggle project explorer', exact:true}).click();
  await expect(page.locator('.explorer')).toHaveCount(0);
  await page.getByRole('button', {name:'Toggle project explorer', exact:true}).click();
  await expect(page.locator('.explorer')).toBeVisible();
});
