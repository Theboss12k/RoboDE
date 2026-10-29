import { test, expect, type Page } from "@playwright/test";

async function workspace(page: Page) {
  await page.goto("/login");
  await page
    .getByLabel("Workspace access code")
    .fill("hosted-browser-test-code");
  await page
    .getByRole("button", { name: "Open workspace", exact: true })
    .click();
  const result = await page.request.post("/api/projects", {
    data: {
      name: `Continuous controls ${Date.now()}`,
      source: "apple_transfer",
    },
  });
  expect(result.status(), await result.text()).toBe(201);
  const project = await result.json();
  await page.addInitScript(
    (id) => localStorage.setItem("robot-ide.project", id),
    project.id,
  );
  await page.reload();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  const before = await (
    await page.request.get(`/api/projects/${project.id}`)
  ).json();
  return { id: project.id, before };
}
async function editor(page: Page) {
  let sid = "";
  page.on("response", async (response) => {
    if (
      /\/api\/projects\/[^/]+\/controls$/.test(response.url()) &&
      response.status() === 201
    )
      sid = (await response.json()).id;
  });
  await page.locator(".scene-robot-picker button").first().click();
  const panel = page.getByRole("region", { name: "Robot virtual controls" });
  await expect(
    panel.getByText("Connected · simulated feedback", { exact: true }),
  ).toBeVisible();
  await expect.poll(() => sid).not.toBe("");
  return { panel, sid };
}
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
});

test("joint slider moves both simulator models while the pointer is still held", async ({
  page,
}) => {
  const { id, before } = await workspace(page);
  const { panel } = await editor(page);
  const slider = panel.getByLabel("Joint target slider", { exact: true });
  await slider.scrollIntoViewIfNeeded();
  const canvas = page.locator(".environment-scene canvas");
  const mini = panel.locator("canvas");
  const original = await canvas.screenshot(),
    originalMini = await mini.screenshot();
  const bounds = (await slider.boundingBox())!;
  const min = Number(await slider.getAttribute("min")),
    max = Number(await slider.getAttribute("max"));
  const x = (value: number) =>
    bounds.x + 8 + ((value - min) / (max - min)) * (bounds.width - 16);
  const y = bounds.y + bounds.height / 2;
  await page.mouse.move(x(Number(await slider.inputValue())), y);
  await page.mouse.down();
  try {
    await page.mouse.move(x(0.55), y, { steps: 12 });
    await expect
      .poll(async () =>
        Number(
          (await panel.locator(".joint-value span").innerText()).split(" ")[0],
        ),
      )
      .toBeGreaterThan(0.35);
    await expect(slider).toBeEnabled();
    expect(await canvas.screenshot()).not.toEqual(original);
    expect(await mini.screenshot()).not.toEqual(originalMini);
  } finally {
    await page.mouse.up();
  }
  await expect(panel).toHaveAttribute("aria-busy", "false");
  const unchanged = await (
    await page.request.get(`/api/projects/${id}`)
  ).json();
  expect(unchanged.state.positions).toEqual(before.state.positions);
  expect(unchanged.instance).toEqual(before.instance);
  await panel.getByRole("button", { name: "Revert", exact: true }).click();
});

test("continuous targets coalesce behind a slow adapter and Stop clears unsent motion", async ({
  page,
}) => {
  const { id } = await workspace(page);
  const { panel, sid } = await editor(page);
  const calls: number[] = [];
  let release: (() => void) | undefined;
  let gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/controls/${sid}/standard-command`, async (route) => {
    calls.push(route.request().postDataJSON().value);
    const response = await route.fetch();
    if (calls.length === 1 || calls.length === 3) await gate;
    await route.fulfill({ response });
  });
  try {
    const input = panel.getByLabel("Preview joint target", { exact: true });
    await input.fill(".1");
    await expect.poll(() => calls.length).toBe(1);
    await input.fill(".2");
    await input.fill(".3");
    await input.fill(".4");
    expect(calls).toEqual([0.1]);
    await expect(input).toBeEnabled();
    release!();
    await expect(panel.locator(".joint-value")).toContainText("0.4000 rad");
    await expect(panel).toHaveAttribute("aria-busy", "false");
    expect(calls).toEqual([0.1, 0.4]);
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await input.fill(".5");
    await expect.poll(() => calls.length).toBe(3);
    await input.fill(".6");
    await panel.getByRole("button", { name: "Stop", exact: true }).click();
    await expect(
      panel.getByText("Stopped · confirmed by simulated feedback", {
        exact: true,
      }),
    ).toBeVisible();
    release!();
    await expect(panel).toHaveAttribute("aria-busy", "false");
    const stopped = await (
      await page.request.get(`/api/controls/${sid}`)
    ).json();
    expect(stopped.stop_requested).toBe(true);
    expect(stopped.feedback.positions.base_yaw).toBeCloseTo(0.5);
    expect(calls).toEqual([0.1, 0.4, 0.5]);
    await panel
      .getByRole("button", { name: "Use as starting point", exact: true })
      .click();
    await expect(panel).toHaveCount(0);
    const applied = await (
      await page.request.get(`/api/projects/${id}`)
    ).json();
    expect(
      applied.instance.initial_configuration.actuator_positions.base_yaw,
    ).toBeCloseTo(0.5);
    expect(applied.state.positions.base_yaw).toBeCloseTo(0.5);
  } finally {
    release?.();
  }
});

test("tool coordinates use IK automatically and invalid targets retain the last valid pose", async ({
  page,
}) => {
  const { id, before } = await workspace(page);
  const { panel, sid } = await editor(page);
  await panel.getByRole("tab", { name: "End effector", exact: true }).click();
  const z = panel.getByLabel("Tool target Z", { exact: true });
  await expect(z).toBeEnabled();
  const originalZ = Number(await z.inputValue());
  await z.fill(String(originalZ + 0.01));
  await expect(panel).toHaveAttribute("aria-busy", "false");
  await expect
    .poll(async () => {
      const poses = await (
        await page.request.get(`/api/controls/${sid}/tool-poses`)
      ).json();
      return poses.positions.parallel_gripper[2];
    })
    .toBeCloseTo(originalZ + 0.01, 3);
  const valid = await (await page.request.get(`/api/controls/${sid}`)).json();
  await z.fill("999");
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(panel).toHaveAttribute("aria-busy", "false");
  const rejected = await (
    await page.request.get(`/api/controls/${sid}`)
  ).json();
  expect(rejected.feedback.positions).toEqual(valid.feedback.positions);
  expect(
    (await (await page.request.get(`/api/projects/${id}`)).json()).state
      .positions,
  ).toEqual(before.state.positions);
  await panel.getByRole("button", { name: "Revert", exact: true }).click();
});

test("Revert cancels pending movement and late responses cannot reopen the preview", async ({
  page,
}) => {
  const { id, before } = await workspace(page);
  const { panel, sid } = await editor(page);
  let calls = 0,
    release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/controls/${sid}/standard-command`, async (route) => {
    calls++;
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await panel.getByLabel("Preview joint target", { exact: true }).fill(".2");
    await expect.poll(() => calls).toBe(1);
    await panel.getByLabel("Preview joint target", { exact: true }).fill(".4");
    await panel.getByRole("button", { name: "Revert", exact: true }).click();
    await expect(panel).toHaveCount(0);
    release();
    expect((await page.request.get(`/api/controls/${sid}`)).status()).toBe(422);
    expect(calls).toBe(1);
    expect(
      (await (await page.request.get(`/api/projects/${id}`)).json())
        .fingerprint,
    ).toBe(before.fingerprint);
  } finally {
    release();
  }
});

test("connected simulator shows intermediate feedback during a command and follows the newest target", async ({
  page,
}) => {
  const { id } = await workspace(page);
  await page.route(`**/api/projects/${id}`, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch(),
      detail = await response.json();
    await route.fulfill({
      response,
      json: {
        ...detail,
        adapter: "isaac_sim",
        worker: { scene_editing: true },
      },
    });
  });
  await page.route(`**/api/projects/${id}/controls`, async (route) => {
    await route.continue({
      postData: JSON.stringify({
        ...route.request().postDataJSON(),
        adapter_id: "mock",
      }),
    });
  });
  await page.reload();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page
    .locator(".native-controls")
    .getByRole("button", { name: /^Control / })
    .first()
    .click();
  const controls = page.locator(".native-controls .adapter-controls");
  await controls
    .getByRole("button", { name: "Connect controls", exact: true })
    .click();
  await expect(
    controls.getByRole("button", { name: "Disconnect controls", exact: true }),
  ).toBeVisible();
  const mini = controls.locator("canvas"),
    main = page.locator(".environment-scene canvas");
  const beforeMini = await mini.screenshot(),
    beforeMain = await main.screenshot();
  let finished = false;
  page.on("response", (response) => {
    if (/\/controls\/[^/]+\/command$/.test(response.url())) finished = true;
  });
  await controls.getByLabel("Control base_yaw", { exact: true }).fill("1.2");
  await expect
    .poll(async () =>
      Number(
        (
          await controls
            .getByLabel("Feedback base_yaw", { exact: true })
            .innerText()
        ).split(" ")[0],
      ),
    )
    .toBeGreaterThan(0.05);
  expect(finished).toBe(false);
  await expect(
    controls.getByLabel("Control base_yaw slider", { exact: true }),
  ).toBeEnabled();
  await controls.getByLabel("Control base_yaw", { exact: true }).fill(".4");
  expect(await mini.screenshot()).not.toEqual(beforeMini);
  expect(await main.screenshot()).not.toEqual(beforeMain);
  await expect(
    controls.getByLabel("Feedback base_yaw", { exact: true }),
  ).toContainText("0.4000", { timeout: 10000 });
  await expect(controls).toHaveAttribute("aria-busy", "false");
  expect(
    Number(
      await controls
        .getByLabel("Control base_yaw", { exact: true })
        .inputValue(),
    ),
  ).toBeCloseTo(0.4);
  expect(
    (await (await page.request.get(`/api/projects/${id}`)).json()).state
      .positions.base_yaw,
  ).toBeCloseTo(0.4);
  await controls
    .getByRole("button", { name: "Disconnect controls", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Robots workspace", exact: true })
    .click();
  await page.unrouteAll({ behavior: "wait" });
});
