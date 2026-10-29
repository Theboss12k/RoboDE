import { test, expect } from "@playwright/test";

// Let in-flight polling mocks finish before Playwright disposes their responses.
test.afterEach(async ({page}) => { await page.unrouteAll({behavior:'wait'}); });

test("business user reviews named transfer, runs shared simulation and sees the result", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("./");
  await expect(
    page.getByRole("heading", { name: "A clear view. A simple command." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Floor plan", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "View asset Apple" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Map asset Apple", exact: true })
    .click();
  await expect(page.locator(".selected-asset")).toContainText("Apple");
  await page
    .getByRole("textbox", { name: "Your command" })
    .fill("MOVE APPLE FROM TABLE1 TO TABLE2");
  await page.getByRole("button", { name: "Review command" }).click();
  await expect(page.getByLabel("Command review")).toContainText(
    "Ready for review",
  );
  await expect(
    page.getByRole("button", { name: "Start simulation" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start simulation" }).click();
  await expect(
    page
      .getByLabel("Command review")
      .getByRole("heading", { name: "Completed" }),
  ).toBeVisible({ timeout: 20000 });
  // The map must agree with the completed run, not leave the apple on Table1.
  const apple = page.getByRole('button', {name:'Map asset Apple', exact:true}).locator('rect');
  const table2 = page.getByRole('button', {name:'Map asset Table2', exact:true}).locator('rect');
  await expect.poll(async () => {
    const center = async (locator: typeof apple) => locator.evaluate(el => ({
      x: Number(el.getAttribute('x')) + Number(el.getAttribute('width')) / 2,
      y: Number(el.getAttribute('y')) + Number(el.getAttribute('height')) / 2,
    }));
    const a = await center(apple), b = await center(table2);
    return Math.hypot(a.x - b.x, a.y - b.y);
  }).toBeLessThan(.03);
  await page.screenshot({
    path: "artifacts/business-desktop.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("phone layout captures a photo, releases camera, and retains room capture", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    permissions: ["camera"],
  });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("./");
  await page.getByRole("button", { name: "Room capture", exact: true }).click();
  await page.getByLabel("Room name").fill("Phone capture test");
  await page.getByRole("button", { name: "New room capture" }).click();
  await expect(
    page.getByRole("button", { name: "Open phone camera" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open phone camera" }).click();
  await expect(page.getByRole("button", { name: "Take photo" })).toBeEnabled({
    timeout: 10000,
  });
  await page.getByRole("button", { name: "Take photo" }).click();
  await expect(page.getByText("1 photos saved this session")).toBeVisible();
  await page.getByRole("button", { name: "Close room camera" }).click();
  await expect(page.getByLabel("Room camera")).toHaveCount(0);
  await expect(
    page.getByText("1 photos added · 12 MB per photo"),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "Room capture", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /Phone capture test/ }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/business-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await context.close();
});

test("voice fills an editable command without executing it", async ({
  page,
}) => {
  await page.addInitScript(() => {
    class Recognition {
      lang = "";
      interimResults = false;
      continuous = false;
      onresult: any;
      onerror: any;
      onend: any;
      start() {
        setTimeout(() => {
          this.onresult?.({ results: [[{ transcript: "Move home" }]] });
          this.onend?.();
        }, 100);
      }
      stop() {
        this.onend?.();
      }
      abort() {}
    }
    (window as any).SpeechRecognition = Recognition;
  });
  let submissions = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/commands/.test(r.url())) submissions++;
  });
  await page.goto("./");
  await page.getByRole("button", { name: "Speak a command" }).click();
  await expect(page.getByRole("textbox", { name: "Your command" })).toHaveValue(
    "Move home",
  );
  expect(submissions).toBe(0);
});

test('command failure stays beside the command controls on a scrolled phone view', async({browser})=>{
 const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});const page=await context.newPage();
 try {
  await page.route('**/commands',route=>route.request().method()==='POST'?route.fulfill({status:422,json:{detail:'Apple is outside this robot’s reachable workspace.'}}):route.continue());
  await page.goto('./');await expect(page.getByRole('dialog',{name:'Hello.'})).toHaveCount(0);
  await page.getByLabel('Your command').fill('MOVE APPLE TO TABLE2');
  await page.getByRole('button',{name:'Review command',exact:true}).click();
  const warning=page.getByRole('alert');await expect(warning).toContainText('reachable workspace');
  const box=await warning.boundingBox();expect(box!.y).toBeGreaterThanOrEqual(0);expect(box!.y+box!.height).toBeLessThanOrEqual(844);
  expect(await warning.evaluate(el=>getComputedStyle(el).position)).toBe('static');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'artifacts/qa-20261027/business-warning-phone.png',fullPage:true});
 } finally {await context.close();}
});

test('business layouts use the shared palette with accessible touch controls',async({page})=>{
 await page.goto('./');await expect(page.getByRole('dialog',{name:'Hello.'})).toHaveCount(0);
 await expect(page.getByLabel('Your command')).toBeVisible();
 for(const width of [320,390,768,1440]) {
  await page.setViewportSize({width,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const small=await page.locator('button:visible').evaluateAll(elements=>elements.filter(el=>{const r=el.getBoundingClientRect();return r.width<43.5||r.height<43.5}).map(el=>el.getAttribute('aria-label')||el.textContent));
  expect(small).toEqual([]);
  await page.screenshot({path:`artifacts/qa-20261027/business-${width}.png`,fullPage:true});
 }
 expect(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--ui-surface').trim())).toBe('#111722');
});

test('denied microphone and camera permissions leave visible recovery messages',async({page})=>{
 await page.addInitScript(()=>{
  class Recognition {
   onerror:any;onend:any;start(){setTimeout(()=>{this.onerror?.({error:'not-allowed'});this.onend?.();},50)}stop(){}abort(){}
  }
  (window as any).SpeechRecognition=Recognition;
  Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>{throw new DOMException('Camera permission denied. Allow access in browser settings.','NotAllowedError')}});
 });
 await page.goto('./');await page.getByRole('button',{name:'Speak a command',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('Microphone access was denied');
 await page.getByRole('button',{name:'Dismiss error',exact:true}).click();
 await page.getByRole('button',{name:'Room capture',exact:true}).click();
 await page.getByLabel('Room name').fill('Permission recovery');await page.getByRole('button',{name:'New room capture',exact:true}).click();
 await page.getByRole('button',{name:'Open phone camera',exact:true}).click();
 const camera=page.getByLabel('Room camera',{exact:true});
 await expect(camera.getByRole('alert')).toContainText('Camera permission denied');
 await expect(camera.getByRole('button',{name:'Take photo',exact:true})).toBeDisabled();
 await camera.getByRole('button',{name:'Close room camera',exact:true}).click();await expect(camera).toHaveCount(0);
});

test('cloud capacity failures stay visible beside the start button without silently retrying',async({page})=>{
 let starts=0;
 await page.route('**/api/business/projects/*/workspace',async route=>{
  const response=await route.fetch();const workspace=await response.json();
  await route.fulfill({response,json:{...workspace,backend:'isaac_sim',connected:false,source:'configured_preview'}});
 });
 await page.route('**/api/business/gpu',route=>route.fulfill({json:{configured:true,status:starts?'error':'stopped',message:starts?'ZONE_RESOURCE_POOL_EXHAUSTED: L4 unavailable':'GPU is stopped.',idle_minutes:10,max_session_minutes:120}}));
 await page.route('**/api/business/gpu/start',route=>{starts++;return route.fulfill({status:202,json:{configured:true,status:'starting',message:'Starting GPU…'}})});
 await page.goto('./');const button=page.getByRole('button',{name:'Start GPU processing',exact:true});await expect(button).toBeVisible();expect(starts).toBe(0);await button.click();
 const warning=page.getByRole('alert');await expect(warning).toContainText('GPU capacity is unavailable',{timeout:10000});
 const box=await warning.boundingBox();expect(box!.y).toBeGreaterThanOrEqual(0);expect(box!.y+box!.height).toBeLessThanOrEqual(page.viewportSize()!.height);expect(starts).toBe(1);
 await expect(button).toBeEnabled();
});

test('native simulator branding never overlaps the refresh control on a phone',async({page})=>{
 await page.route('**/api/business/projects/*/workspace',async route=>{const response=await route.fetch();const data=await response.json();await route.fulfill({response,json:{...data,backend:'isaac_sim'}})});
 await page.goto('./');await expect(page.locator('.workspace-location .nvidia-logo')).toBeVisible();
 for(const width of [320,390]) {
  await page.setViewportSize({width,height:844});
  const badge=await page.locator('.workspace-location').boundingBox(),refresh=await page.getByRole('button',{name:'Refresh workspace',exact:true}).boundingBox();
  expect(badge!.x+badge!.width).toBeLessThanOrEqual(refresh!.x);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 }
});
