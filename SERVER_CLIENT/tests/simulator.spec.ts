import { test, expect, type Page } from "@playwright/test";

async function openProject(page: Page) {
  await page.goto("/login");
  await page
    .getByLabel("Workspace access code")
    .fill("hosted-browser-test-code");
  await page
    .getByRole("button", { name: "Open workspace", exact: true })
    .click();
  const config = await page.request.put("/api/configuration/isaac", {
    data: {
      deployment: "remote",
      url: "http://127.0.0.1:9100",
      token: "isolated-browser-worker-token",
    },
  });
  expect(config.ok()).toBeTruthy();
  const response = await page.request.post("/api/projects", {
    data: { name: `Scene handoff ${Date.now()}`, source: "apple_transfer" },
  });
  expect(response.status()).toBe(201);
  const { id } = await response.json();
  await page.addInitScript(
    (id) => localStorage.setItem("robot-ide.project", id),
    id,
  );
  return id;
}

test("switching transfers the whole project and unsaved objects, then returns the observed scene", async ({
  page,
}) => {
  const id = await openProject(page);
  const robot = await page.request.post(`/api/projects/${id}/robots`, {
    data: {
      id: "arm_02",
      name: "Second arm",
      base_pose: { x: 1.2, y: 0.2, z: 0, yaw: 0.4 },
    },
  });
  expect(robot.status()).toBe(201);
  await page.reload();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  const before = await (await page.request.get(`/api/projects/${id}`)).json();
  await page.getByRole("button", { name: "obstacle", exact: true }).click();
  await page
    .locator(".object-form")
    .last()
    .getByRole("textbox")
    .fill("Transfer crate");
  await expect(
    page.getByRole("status").filter({ hasText: "Unsaved scene preview" }),
  ).toBeVisible();
  try {
    await page
      .getByLabel("Simulation backend", { exact: true })
      .selectOption("isaac_sim");
    await expect(
      page.getByText(
        `Scene transferred · 2 robots and ${before.objects.length + 1} objects. Current poses preserved; saved starting points unchanged.`,
        { exact: true },
      ),
    ).toBeVisible();
    await expect(
      page.getByLabel("Simulation backend", { exact: true }),
    ).toHaveValue("isaac_sim");
    await expect(page.locator(".environment-scene canvas")).toBeVisible();
    const native = await (await page.request.get(`/api/projects/${id}`)).json();
    expect(native.worker.engine).toBe("contract_test"); // Transport coverage only.
    expect(native.robots.map((r: any) => r.instance)).toEqual(
      before.robots.map((r: any) => r.instance),
    );
    expect(native.objects.some((o: any) => o.name === "Transfer crate")).toBe(
      true,
    );
    await page
      .getByLabel("Simulation backend", { exact: true })
      .selectOption("mock");
    await expect(
      page.getByLabel("Simulation backend", { exact: true }),
    ).toHaveValue("mock");
    await expect(
      page.locator(".object-form").last().getByRole("textbox"),
    ).toHaveValue("Transfer crate");
    const returned = await (
      await page.request.get(`/api/projects/${id}`)
    ).json();
    expect(returned.objects).toEqual(native.objects);
    expect(returned.robots.map((r: any) => r.state.positions)).toEqual(
      native.robots.map((r: any) => r.state.positions),
    );
  } finally {
    await page.request.put(`/api/projects/${id}/simulation`, {
      data: { adapter: "mock" },
    });
  }
});

test("a rejected switch keeps the selected simulator and explains the missing worker", async ({
  page,
}) => {
  const id = await openProject(page);
  await page.route(`**/api/projects/${id}/simulation`, (route) =>
    route.fulfill({
      status: 502,
      json: {
        detail:
          "Isaac Sim worker is unavailable. Configure the worker connection in Isaac Sim setup.",
      },
    }),
  );
  await page.reload();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page
    .getByLabel("Simulation backend", { exact: true })
    .selectOption("isaac_sim");
  await expect(
    page.getByText(
      "Isaac Sim worker is unavailable. Configure the worker connection in Isaac Sim setup.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByLabel("Simulation backend", { exact: true }),
  ).toHaveValue("mock");
  expect(
    (await (await page.request.get(`/api/projects/${id}`)).json()).adapter,
  ).toBe("mock");
});
