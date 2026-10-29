import { test, expect } from "@playwright/test";
test("global setup imports a reusable robot and adapter before a project pairs and tests them", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const project = await (
    await request.post("/api/projects", {
      data: { name: "Library flow QA", source: "apple_transfer" },
    })
  ).json();
  await page.goto("/");
  await page
    .getByLabel("Select project", { exact: true })
    .selectOption(project.id);
  const before = await (
    await request.get(`/api/projects/${project.id}`)
  ).json();
  const bundle = await (
    await request.get("/api/registry/demo_arm/bundle")
  ).json();
  const mid = "global_ui_" + Date.now();
  bundle.robot = { ...bundle.robot, id: mid, name: "Global UI Robot" };
  await page
    .getByRole("button", { name: "Open configuration", exact: true })
    .click();
  const config = page.getByRole("dialog", {
    name: "Global configuration",
    exact: true,
  });
  await expect(
    config.getByRole("button", { name: "Add robot to project", exact: true }),
  ).toHaveCount(0);
  await config
    .getByRole("button", { name: "Add robot to library", exact: true })
    .click();
  await config
    .getByLabel("Import robot definition", { exact: true })
    .setInputFiles({
      name: "qa.robot.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(bundle)),
    });
  await expect(config.getByLabel("Global robot ID")).toHaveValue(mid);
  await config
    .getByRole("button", { name: "Save global robot & continue", exact: false })
    .click();
  await expect(
    config.getByRole("heading", {
      name: "3. Control adapter for Global UI Robot",
    }),
  ).toBeVisible();
  const unchanged = await (
    await request.get(`/api/projects/${project.id}`)
  ).json();
  expect(unchanged.robots.length).toBe(before.robots.length);
  await config
    .getByRole("button", { name: "Physical · robot hardware", exact: true })
    .click();
  await config
    .getByRole("button", {
      name: "Create adapter from documentation / custom commands",
      exact: true,
    })
    .click();
  const wizard = config.getByRole("dialog", { name: "Adapter setup wizard" });
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();
  await wizard.getByRole("button", { name: /Define custom commands/ }).click();
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();
  await wizard
    .getByLabel("Adapter name", { exact: true })
    .fill("Global Physical SDK QA");
  await wizard.getByRole("button", { name: "Continue", exact: true }).click();
  await wizard
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await wizard
    .getByLabel("I reviewed the generated adapter", { exact: true })
    .check();
  await wizard
    .getByRole("button", {
      name: "Record review & open simulator",
      exact: true,
    })
    .click();
  await expect(
    wizard.getByRole("button", { name: "Disconnect controls", exact: true }),
  ).toBeVisible();
  await expect(wizard.locator(".control-source")).toContainText(/simulat/i);
  await wizard
    .getByRole("button", { name: "Disconnect controls", exact: true })
    .click();
  await wizard
    .getByRole("button", { name: "Close adapter wizard", exact: true })
    .click();
  const adapters = await (
    await request.get(`/api/models/${mid}/adapters`)
  ).json();
  const aid = adapters.find((a: any) => a.name === "Global Physical SDK QA").id;
  await page.screenshot({ path: "artifacts/global-robot-library.png" });
  await config
    .getByRole("button", { name: "Close configuration", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Robots workspace", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Add robot instance", exact: true })
    .click();
  const add = page.getByRole("dialog", {
    name: "Add project robot",
    exact: true,
  });
  await add.getByLabel("New robot model", { exact: true }).selectOption(mid);
  await add.getByLabel("New robot ID", { exact: true }).fill("library_arm");
  await add
    .getByLabel("New robot name", { exact: true })
    .fill("Library instance");
  await add
    .getByRole("button", { name: "Continue to adapter", exact: true })
    .click();
  await add
    .getByRole("button", { name: "Physical · hardware", exact: true })
    .click();
  await add
    .getByLabel("Project robot adapter", { exact: true })
    .selectOption(aid);
  await add
    .getByRole("button", { name: "Add instance & test", exact: true })
    .click();
  await expect(page.locator(".robot-editor .adapter-controls")).toBeVisible();
  await expect(
    page
      .locator(".robot-editor")
      .getByLabel("Project robot adapter", { exact: true }),
  ).toHaveValue(aid);
  await page
    .getByRole("button", { name: "Connect controls", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Disconnect controls", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Disconnect controls", exact: true })
    .click();
  await page.reload();
  await page
    .getByRole("button", { name: "Robots workspace", exact: true })
    .click();
  await page
    .locator(".instance-list")
    .getByRole("button", { name: /Library instance/ })
    .click();
  await expect(
    page.getByLabel("Project robot adapter", { exact: true }),
  ).toHaveValue(aid);
  const saved = await (await request.get(`/api/projects/${project.id}`)).json();
  expect(
    saved.robots.find((r: any) => r.instance.instance.id === "library_arm")
      .instance.control_adapter,
  ).toMatchObject({ adapter_id: aid, category: "physical" });
  await page.screenshot({ path: "artifacts/project-robot-pairing.png" });
});
