import {expect, type Page} from '@playwright/test';

export async function checkWelcome(page: Page, product: 'ide' | 'business') {
  const greeting = page.getByRole('dialog', {name: 'Hello.'});
  await expect(greeting).toBeVisible();
  await expect(greeting.getByText('Plan, control and command your robot.', {exact:true})).toBeVisible();
  await expect(greeting.getByRole('button', {name: 'Continue'})).toBeFocused();
  const buttonSize = await greeting.getByRole('button', {name:'Continue'}).boundingBox();
  expect(buttonSize!.height).toBeGreaterThanOrEqual(44);
  expect(buttonSize!.width).toBeGreaterThanOrEqual(44);
  expect(await page.locator('.welcome-content').evaluate(el => el.hasAttribute('inert'))).toBe(true);
  // Freeze CSS only for a deterministic visual reference; auto-dismiss still runs normally.
  await page.screenshot({path: `artifacts/ui-final/${product}-welcome.png`, animations: 'disabled'});
  await page.keyboard.press('Tab');
  await expect(greeting.getByRole('button', {name: 'Continue'})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(greeting).toHaveCount(0);
  await expect(page.locator('.welcome-content')).toBeFocused();
  expect(await page.locator('.welcome-content').evaluate(el => el.hasAttribute('inert'))).toBe(false);
  await page.reload({waitUntil:'domcontentloaded'});
  await expect(greeting).toBeVisible();
  await expect(greeting).toHaveCount(0, {timeout: 5000});
  await page.emulateMedia({reducedMotion: 'reduce'});
  await page.reload({waitUntil:'domcontentloaded'});
  await expect(greeting).toBeVisible();
  expect(await greeting.evaluate(el => getComputedStyle(el).animationName)).toBe('none');
  await greeting.getByRole('button', {name: 'Continue'}).click();
  await expect(greeting).toHaveCount(0);
}
