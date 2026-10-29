import {test,expect} from '@playwright/test';
test('Business App installs from accessible instructions and exposes valid metadata',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/business/');
  const install=page.getByRole('button',{name:'Install Business App'});
  await install.click();
  const dialog=page.getByRole('dialog',{name:'Install RoboDE Business'});
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Add to Home Screen');
  await expect(page.getByRole('button',{name:'Close install instructions'})).toBeFocused();
  await page.keyboard.press('Shift+Tab');await expect(dialog.getByRole('button',{name:'Done',exact:true})).toBeFocused();
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(install).toBeFocused();
  const manifest=await (await page.request.get('/business/manifest.webmanifest')).json();
  expect(manifest.scope).toBe('/business/');expect(manifest.display).toBe('standalone');
  for(const icon of manifest.icons)expect((await page.request.get(icon.src)).ok()).toBeTruthy();
  await page.setViewportSize({width:390,height:844});await install.click();await expect(dialog).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await dialog.getByRole('button',{name:'Done',exact:true}).click();await expect(dialog).toHaveCount(0);
});
