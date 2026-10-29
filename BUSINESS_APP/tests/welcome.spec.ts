import {test, expect} from '@playwright/test';
import {checkWelcome} from '../../tests/welcome-check';

test('phone welcome supports touch, keyboard, reload and reduced motion', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.goto('./');
  await checkWelcome(page, 'business');
  await page.getByRole('button', {name: 'Room capture', exact: true}).click();
  await expect(page.getByRole('dialog', {name: 'Hello.'})).toHaveCount(0);
  await page.setViewportSize({width: 667, height: 375});
  await page.reload();
  const button = page.getByRole('button', {name: 'Continue', exact: true});
  await expect(button).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await button.click();
});
