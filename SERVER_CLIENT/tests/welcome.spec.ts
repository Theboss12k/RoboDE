import {test, expect} from '@playwright/test';
import {checkWelcome} from '../../tests/welcome-check';

test('welcome is keyboard accessible, dismisses automatically and returns on browser reload', async ({page}) => {
  await page.request.post('/login', {form:{code:'hosted-browser-test-code'}});
  await page.goto('/', {waitUntil:'domcontentloaded'});
  await checkWelcome(page, 'ide');
  for (const name of ['Robots', 'Environment', 'Plans']) {
    await page.getByRole('button', {name: `${name} workspace`, exact: true}).click();
    await expect(page.getByRole('dialog', {name: 'Hello.'})).toHaveCount(0);
  }
});
