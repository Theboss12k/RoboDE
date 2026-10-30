import { test, expect, type Page } from "@playwright/test";
async function openGlobalAdapterWizard(page: Page) {
  await page
    .getByRole("button", { name: "Open configuration", exact: true })
    .click();
  const legacy=page.getByText("Legacy robot definitions & adapters", {exact:true});
  if(await legacy.count() && !(await legacy.locator("..").evaluate(el=>el.hasAttribute("open")))) await legacy.click();
  await page
    .getByRole("dialog", { name: "Global configuration", exact: true })
    .getByRole("button", { name: "Configure adapters & test", exact: true })
    .first()
    .click();
  await page
    .getByRole("button", {
      name: "Create adapter from documentation / custom commands",
      exact: true,
    })
    .click();
}
const created: string[] = [];
const controlSessions: string[] = [];
const initial = {
  base_yaw: 0,
  shoulder: 1,
  elbow: -1.8,
  wrist: 0.8,
  gripper: 0.08,
};
const objects = [
  {
    id: "apple",
    name: "Apple",
    kind: "object",
    position: { x: 0.34, y: -0.16, z: 0.065 },
    size: { x: 0.065, y: 0.065, z: 0.065 },
    mass_kg: 0.08,
  },
  {
    id: "basket",
    name: "Basket",
    kind: "region",
    position: { x: 0.27, y: 0.27, z: 0.08 },
    size: { x: 0.18, y: 0.18, z: 0.14 },
    mass_kg: 0,
  },
];
test.beforeEach(async ({ page, request }) => {
  const response = await request.post("/api/projects", {
    data: { name: "E2E workflow", source: "apple_transfer" },
  });
  expect(response.status()).toBe(201);
  const project = await response.json();
  created.push(project.id);
  await request.put(`/api/projects/${project.id}/simulation`, {
    data: { adapter: "mock" },
  });
  const detail = await (
    await request.get(`/api/projects/${project.id}`)
  ).json();
  for (const [index, robot] of detail.robots.entries()) {
    expect(
      (
        await request.put(
          `/api/projects/${project.id}/robots/${robot.instance.instance.id}/placement`,
          { data: { x: 0, y: index * 1.3, z: 0, yaw: 0 } },
        )
      ).ok(),
    ).toBeTruthy();
    expect(
      (
        await request.put(`/api/projects/${project.id}/initial`, {
          data: { robot_id: robot.instance.instance.id, positions: initial },
        })
      ).ok(),
    ).toBeTruthy();
  }
  expect(
    (
      await request.put(`/api/projects/${project.id}/world`, {
        data: { objects },
      })
    ).ok(),
  ).toBeTruthy();
  expect(
    (await request.post(`/api/projects/${project.id}/reset`)).ok(),
  ).toBeTruthy();
  await page.addInitScript(
    (id) => localStorage.setItem("robot-ide.project", id),
    project.id,
  );
  page.on("response", async (r) => {
    if (/\/api\/(?:projects\/[^/]+|library\/robots\/[^/]+)\/controls$/.test(r.url()) && r.status() === 201)
      controlSessions.push((await r.json()).id);
  });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Plans workspace", exact: true }),
  ).toBeVisible();
});
test.afterEach(async ({ request, page }) => {
  // Polling requests can be cancelled when the route-backed preview unmounts.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  for (const id of controlSessions.splice(0))
    await request.delete(`/api/controls/${id}`);
});
async function newPlan(page: Page, name = "Apple transfer plan") {
  await page
    .getByRole("button", { name: "New plan", exact: true })
    .first()
    .click();
  await page.getByLabel("New plan name", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Create plan", exact: true }).click();
  await expect(page.getByLabel("Plan name", { exact: true })).toHaveValue(name);
  await page.getByRole("button", {name:"Legacy goal editor",exact:true}).click();
}
async function compiled(page: Page) {
  await newPlan(page);
  await page
    .getByRole("button", { name: "Generate tasks", exact: true })
    .click();
  await expect(page.locator(".atomic-task")).toHaveCount(9);
  await expect(page.getByLabel("Task type", { exact: true })).toHaveValue(
    "command",
  );
  await expect(
    page.getByLabel("Standard command type", { exact: true }),
  ).toHaveValue("MOVE_END_EFFECTOR");
  await page.getByRole("button", { name: "Validate plan", exact: true }).click();
  await expect(
    page.getByText("Ready for simulation", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Validate plan", exact: true }),
  ).toBeEnabled();
  await expect(page.getByLabel("Plan goal", { exact: true })).toHaveValue(
    "Pick up the apple and place it in the basket.",
  );
}

test("hierarchy, atomic tasks, immutable code, simulation and history", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await compiled(page);
  await expect(page.locator(".task-tree>button")).toHaveCount(9);
  await expect(page.locator(".task-node")).toHaveCount(9);
  await page.locator(".atomic-task").first().click();
  await expect(page.getByLabel("Task name", { exact: true })).toHaveValue(
    "Approach object",
  );
  await expect(page.getByLabel("Task robot", { exact: true })).toHaveValue(
    "arm_01",
  );
  await page.screenshot({ path: "artifacts/simplified-plans.png" });
  await page.getByRole("tab", { name: "Generated code", exact: true }).click();
  await expect(page.locator(".monaco-editor")).toBeVisible();
  await expect(page.locator(".code-bar")).toContainText("/revisions/");
  await page.getByRole("button", { name: "Run simulation", exact: true }).click();
  await expect(page.locator(".run-status.success")).toHaveText(
    "simulation passed",
    { timeout: 25000 },
  );
  await expect(page.locator(".execution-panel")).toContainText(
    "Postconditions: passed",
  );
  await expect(page.locator(".execution-panel")).toContainText(
    "Stopped: confirmed",
  );
  await page.getByRole("tab", { name: "Run history", exact: true }).click();
  await expect(page.locator(".runs-list>button")).toHaveCount(1);
  await page.locator(".runs-list>button").click();
  await expect(page.locator(".run-status.success")).toBeVisible();
  expect(errors).toEqual([]);
});

test("robot browsing does not change task assignments and edits require compilation", async ({
  page,
}) => {
  await compiled(page);
  await page
    .getByRole("button", { name: "Robots workspace", exact: true })
    .click();
  await page.locator(".instance-list>button").nth(1).click();
  await page
    .getByRole("button", { name: "Plans workspace", exact: true })
    .click();
  await expect(page.getByLabel("Task robot", { exact: true })).toHaveValue(
    "arm_01",
  );
  await page
    .getByLabel("Task name", { exact: true })
    .fill("Approach carefully");
  await expect(
    page.getByRole("button", { name: "Run simulation", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.reload();
  await expect(page.getByLabel("Task name", { exact: true })).toHaveValue(
    "Approach carefully",
  );
  await expect(
    page.getByRole("button", { name: "Run simulation", exact: true }),
  ).toBeDisabled();
});

test("saved robot configuration stays separate from actual feedback and environment", async ({
  page,
  request,
}) => {
  await compiled(page);
  const id = await page
    .getByLabel("Select project", { exact: true })
    .inputValue();
  await page
    .getByRole("button", { name: "Robots workspace", exact: true })
    .click();
  await page.getByText("Saved starting configuration", { exact: true }).click();
  await page.getByLabel("Initial base_yaw", { exact: true }).fill(".1");
  await page
    .getByRole("button", { name: "Save configuration", exact: true })
    .click();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Actual simulation state is unchanged" }),
  ).toBeVisible();
  const data = await (await request.get(`/api/projects/${id}`)).json();
  expect(data.robots[0].state.positions.base_yaw).toBe(0);
  expect(
    data.robots[0].instance.initial_configuration.actuator_positions.base_yaw,
  ).toBe(0.1);
  await page
    .getByRole("button", { name: "Plans workspace", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Run simulation", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await expect(
    page.getByLabel("Simulation backend", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Initial base_yaw", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Reset simulator", exact: true })
    .click();
  await expect(
    page.getByRole("status").filter({ hasText: "Simulator reset" }),
  ).toBeVisible();
  const updated = await (await request.get(`/api/projects/${id}`)).json();
  expect(updated.robots[0].state.positions.base_yaw).toBe(0.1);
});

test("environment disconnect stays disconnected and an unreachable Isaac worker preserves local backend", async ({
  page,
  request,
}) => {
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(
    page.locator(".environment-scene .viewport-badge"),
  ).toContainText("DISCONNECTED");
  const id = await page
    .getByLabel("Select project", { exact: true })
    .inputValue();
  expect(
    (await (await request.get(`/api/projects/${id}`)).json())
      .environment_connected,
  ).toBe(false);
  await page
    .getByRole("button", { name: "Connect / read state", exact: true })
    .click();
  await expect(
    page.locator(".environment-scene .viewport-badge"),
  ).toContainText("BUILT-IN");
  await page
    .getByLabel("Simulation backend", { exact: true })
    .selectOption("isaac_sim");
  await expect(page.getByRole("alert")).toContainText("worker");
  await expect(
    page.getByLabel("Simulation backend", { exact: true }),
  ).toHaveValue("mock");
  await page.screenshot({ path: "artifacts/simplified-environment.png" });
});

test("physical ROS adapter wizard generates, reviews, tests and controls through simulated transport", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Robots workspace", exact: true })
    .click();
  await openGlobalAdapterWizard(page);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: /Define custom commands/ }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByLabel("Adapter interface", { exact: true })
    .selectOption("ros2");
  await page
    .getByLabel("Adapter name", { exact: true })
    .fill("E2E generated ROS adapter");
  await page
    .getByLabel("ROS bridge URL", { exact: true })
    .fill("http://127.0.0.1:1");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.locator(".adapter-source").first()).toContainText(
    "class Adapter",
  );
  await page
    .getByLabel("I reviewed the generated adapter", { exact: true })
    .check();
  await page
    .getByRole("button", {
      name: "Record review & open simulator",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("button", { name: "Test Wave", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Test Wave", exact: true }).click();
  await expect(page.locator(".command-result")).toContainText("wave · passed", {
    timeout: 15000,
  });
  await expect(page.locator(".command-result")).toContainText(
    "stopped confirmed",
  );
  await page.screenshot({ path: "artifacts/adapter-command-test-window.png" });
  await expect(page.locator(".test-report")).toContainText(
    "Simulated contract tests passed",
  );
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page
    .getByRole("button", { name: "Close configuration", exact: true })
    .click();
  const adapters = await (
    await page.request.get("/api/models/demo_arm/adapters")
  ).json();
  const adapterId = adapters.find(
    (a: any) => a.name === "E2E generated ROS adapter",
  ).id;
  await page.getByRole("group", {name:"Project robot target",exact:true})
    .getByRole("button", { name: "Physical · hardware", exact: true })
    .click();
  await page
    .getByLabel("Project robot adapter", { exact: true })
    .selectOption(adapterId);
  await page
    .getByRole("button", { name: "Save robot–adapter pairing", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Test selected adapter", exact: true })
    .click();
  await expect(page.getByLabel("Control target", { exact: true })).toHaveValue(
    "test",
  );
  await page
    .getByRole("button", { name: "Connect controls", exact: true })
    .click();
  await expect(page.getByRole('button',{name:'Disconnect controls',exact:true})).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Increase base_yaw", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Increase base_yaw", exact: true })
    .click();
  await expect(
    page.getByLabel("Feedback base_yaw", { exact: true }),
  ).toContainText("0.0500");
  await expect(page.locator(".control-source")).toContainText(
    "No physical connection",
  );
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(page.locator(".control-feedback")).toContainText(
    "Stopped: confirmed",
  );
  await page.screenshot({ path: "artifacts/adapter-controls.png" });
  await page
    .getByRole("button", { name: "Disconnect controls", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page.locator(".scene-robot-picker button").first().click();
  const preview = page.getByRole("region", { name: "Robot virtual controls" });
  await expect(
    preview.getByText("Connected · simulated feedback", { exact: true }),
  ).toBeVisible();
  await expect(
    preview
      .getByLabel("Robot preview adapter", { exact: true })
      .locator("option:checked"),
  ).toContainText("E2E generated ROS adapter");
  await preview
    .getByRole("button", { name: "Select elbow", exact: true })
    .click();
  await expect(
    preview.getByLabel("Preview actuator", { exact: true }),
  ).toHaveValue("elbow");
  await preview.getByRole("button", { name: "Revert", exact: true }).click();
});

test("unsupported task requests fail explicitly and stop confirms cancellation", async ({
  page,
}) => {
  await newPlan(page);
  await page
    .getByLabel("Goal 1", { exact: true })
    .fill("Throw the apple into the basket.");
  await page
    .getByRole("button", { name: "Generate tasks", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("unavailable");
  await expect(page.locator(".atomic-task")).toHaveCount(0);
  await page
    .getByLabel("Goal 1", { exact: true })
    .fill("Pick up the apple and place it in the basket.");
  await page
    .getByRole("button", { name: "Generate tasks", exact: true })
    .click();
  await expect(page.locator(".atomic-task")).toHaveCount(9);
  await page.getByRole("button", { name: "Validate plan", exact: true }).click();
  await expect(
    page.getByText("Ready for simulation", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Run simulation", exact: true }).click();
  await page
    .getByRole("button", { name: "Stop simulation", exact: true })
    .first()
    .click();
  await expect(page.locator(".run-status")).toHaveText("cancelled");
  await expect(page.locator(".execution-panel")).toContainText(
    "Stopped: confirmed",
  );
});

test("two-robot goals expand to atomic tasks and execute with independent verification", async ({
  page,
  request,
}) => {
  const response = await request.post("/api/projects", {
    data: { name: "E2E workflow", source: "dual_arm_cell" },
  });
  const dual = await response.json();
  created.push(dual.id);
  await page.reload();
  await page
    .getByLabel("Select project", { exact: true })
    .selectOption(dual.id);
  await expect(
    page
      .locator(".explorer-reference")
      .getByRole("button")
      .filter({ hasText: "Robots" }),
  ).toContainText("2");
  await newPlan(page, "Two robot transfer");
  await expect(page.getByLabel("Goal 2", { exact: true })).toHaveValue(
    "Pick up the apple 2 and place it in the basket 2.",
  );
  await page
    .getByRole("button", { name: "Generate tasks", exact: true })
    .click();
  await expect(page.locator(".atomic-task")).toHaveCount(18);
  await page.getByRole("button", { name: "Validate plan", exact: true }).click();
  await expect(
    page.getByText("Ready for simulation", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Run simulation", exact: true }).click();
  await expect(page.locator(".run-status.success")).toHaveText(
    "simulation passed",
    { timeout: 25000 },
  );
  await page.screenshot({ path: "artifacts/atomic-multi-robot.png" });
});

test("tutorial covers the simplified workflow and every workspace without mutations, then restores focus and view", async ({
  page,
}) => {
  await compiled(page);
  await page.getByRole("tab", { name: "Generated code", exact: true }).click();
  await expect(page.locator(".monaco-editor")).toBeVisible();
  const mutations: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (r.url().includes("/api/") && r.method() !== "GET")
      mutations.push(r.url());
  });
  await page
    .getByRole("button", { name: "Open tutorial", exact: true })
    .click();
  const count = await page
    .getByLabel("Jump to tutorial section", { exact: true })
    .locator("option")
    .count();
  expect(count).toBeGreaterThanOrEqual(15);
  for (let i = 0; i < count; i++) {
    const card = page.locator(".tutorial-card");
    await expect(
      page.getByLabel(`Tutorial step ${i + 1} of ${count}`, { exact: true }),
    ).toBeVisible();
    await expect
      .poll(async () => {
        const r = await card.boundingBox();
        return r ? r.y + r.height : Infinity;
      })
      .toBeLessThanOrEqual(970);
    await card
      .getByRole("button", {
        name: i === count - 1 ? "Finish" : "Next",
        exact: true,
      })
      .click();
  }
  await expect(page.locator(".tutorial-card")).toHaveCount(0);
  await expect(
    page.getByRole("tab", { name: "Generated code", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
});

test("tutorial supports reduced motion, direct jumps and keyboard dismissal during execution", async ({
  page,
}) => {
  await compiled(page);
  await page.getByRole("button", { name: "Run simulation", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "Simulation", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page
    .getByRole("button", { name: "Open tutorial", exact: true })
    .click();
  await page
    .locator(".tutorial-card")
    .getByRole("button", { name: "Stop simulation", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Close tutorial", exact: true })
    .click();
  await expect(page.locator(".run-status")).toHaveText("cancelled");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page
    .getByRole("button", { name: "Toggle project explorer", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Open tutorial", exact: true })
    .click();
  const menu = page.getByLabel("Jump to tutorial section", { exact: true });
  const value = await menu
    .locator("option")
    .filter({ hasText: "Choose the Planner LLM and Task LLM" })
    .getAttribute("value");
  await menu.selectOption(value!);
  await expect(page.locator(".planner-converter-settings")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".tutorial-card")).toHaveCount(0);
  await expect(page.locator(".explorer")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open tutorial", exact: true }),
  ).toBeFocused();
});

test("editing the plan goal updates the single robot goal used for generation", async ({
  page,
}) => {
  await newPlan(page, "Return home");
  await page.getByLabel("Plan goal", { exact: true }).fill("Move home.");
  await expect(page.getByLabel("Goal 1", { exact: true })).toHaveValue(
    "Move home.",
  );
  await page
    .getByRole("button", { name: "Generate tasks", exact: true })
    .click();
  await expect(page.locator(".atomic-task")).toHaveCount(6);
  await expect(page.getByLabel("Plan goal", { exact: true })).toHaveValue(
    "Move home.",
  );
});

test("new scene objects preview immediately and persist after save", async ({
  page,
  request,
}) => {
  const project = created.at(-1)!;
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page.getByRole("button", { name: "object", exact: true }).click();
  const scene = page.locator(".environment-scene");
  await expect(scene).toHaveAttribute("data-scene-saved", "false");
  await expect
    .poll(
      async () =>
        ((await scene.getAttribute("data-scene-object-ids")) ?? "").split(",")
          .length,
    )
    .toBe(3);
  expect(
    (await (await request.get(`/api/projects/${project}`)).json()).objects,
  ).toHaveLength(2);
  await page
    .getByRole("button", { name: "Focus New object", exact: true })
    .click();
  await page.getByLabel("New object x", { exact: true }).fill(".55");
  await page.getByRole("button", { name: "Save scene", exact: true }).click();
  await expect(scene).toHaveAttribute("data-scene-saved", "true");
  const saved = (await (await request.get(`/api/projects/${project}`)).json())
    .objects;
  expect(saved.at(-1).position.x).toBe(0.55);
  await page.reload();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await expect(page.getByLabel("New object x", { exact: true })).toHaveValue(
    "0.55",
  );
});

test("all four 3D formats load real geometry, save and reload; external glTF is rejected", async ({
  page,
}) => {
  const { obj, stl, gltf, glb } = await import("./modelFixtures");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Import 3D object", exact: true })
    .click();
  let n = 0;
  for (const [format, buffer] of Object.entries({ obj, stl, gltf, glb })) {
    await page.getByLabel("3D model file", { exact: true }).setInputFiles({
      name: `sample_${format}.${format}`,
      mimeType: "application/octet-stream",
      buffer,
    });
    await page
      .getByRole("button", { name: "Import model", exact: true })
      .click();
    n++;
    await expect(page.locator('[data-model-status="loaded"]')).toHaveCount(n);
    await expect(page.locator(".imported-file-label")).toHaveCount(n);
  }
  await page.screenshot({ path: "artifacts/imported-3d-scene.png" });
  await page.getByRole("button", { name: "Save scene", exact: true }).click();
  await expect(page.locator(".environment-scene")).toHaveAttribute(
    "data-scene-saved",
    "true",
  );
  await page.reload();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await expect(page.locator('[data-model-status="loaded"]')).toHaveCount(4);
  await page
    .getByRole("button", { name: "Import 3D object", exact: true })
    .click();
  await page.getByLabel("3D model file", { exact: true }).setInputFiles({
    name: "external.gltf",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({
        asset: { version: "2.0" },
        meshes: [{}],
        buffers: [{ uri: "https://example.com/unsafe.bin" }],
      }),
    ),
  });
  await page.getByRole("button", { name: "Import model", exact: true }).click();
  await expect(page.locator('.model-import [role="alert"]')).toContainText(
    "self-contained",
  );
  expect(errors).toEqual([]);
});

test("configuration imports a global robot before the project creates its configured instance", async ({
  page,
  request,
}) => {
  const bundle = await (
    await request.get("/api/registry/demo_arm/bundle")
  ).json();
  const modelId = "e2e_model_" + Date.now();
  bundle.robot.id = modelId;
  bundle.robot.name = "Imported test arm";
  await page
    .getByRole("button", { name: "Open configuration", exact: true })
    .click();
  await page.getByText("Legacy robot definitions & adapters", {exact:true}).click();
  await page
    .getByRole("button", { name: "Add robot to library", exact: true })
    .click();
  await page
    .getByLabel("Import robot definition", { exact: true })
    .setInputFiles({
      name: "robot.robot.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(bundle)),
    });
  await page
    .getByRole("button", { name: "Save global robot & continue", exact: false })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "3. Control adapter for Imported test arm",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Close configuration", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Robots workspace", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Add robot instance", exact: true })
    .click();
  await page
    .getByLabel("New robot model", { exact: true })
    .selectOption(modelId);
  await page.getByLabel("New robot ID", { exact: true }).fill("configured_arm");
  await page
    .getByLabel("New robot name", { exact: true })
    .fill("Configured robot");
  await page
    .getByText("Optional · initial joints and placement", { exact: true })
    .click();
  await page
    .getByLabel("New robot joint base_yaw", { exact: true })
    .fill(".25");
  await page
    .getByRole("button", { name: "Continue to adapter", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Add instance & test", exact: true })
    .click();
  await expect(page.locator(".robot-editor .adapter-controls")).toBeVisible();
  await page.getByText("Saved starting configuration", { exact: true }).click();
  await expect(
    page.getByLabel("Initial base_yaw", { exact: true }),
  ).toHaveValue("0.25");
  await expect(page.locator(".instance-reference")).toContainText(modelId);
});

test("global LLM functions, per-task selection, refinement and standalone execution", async ({
  page,
  request,
}) => {
  const { createServer } = await import("node:http");
  const calls: any[] = [];
  const server = createServer(async (req, res) => {
    let text = "";
    for await (const part of req) text += part;
    // AI Models checks availability with read-only model-list requests.
    if (req.method === "GET") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ models: [], data: [] }));
      return;
    }
    const body = JSON.parse(text);
    calls.push(body);
    let content = "A recorded LLM answer";
    if (
      body.messages.some(
        (m: any) =>
          m.role === "system" &&
          m.content.includes("Refine exactly one atomic task"),
      )
    ) {
      const system = body.messages.find(
        (m: any) => m.role === "system",
      ).content;
      const task = JSON.parse(system.split("Current task: ")[1]);
      content = JSON.stringify({ ...task, name: "Refined LLM task" });
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ choices: [{ message: { content } }] }));
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const port = (server.address() as { port: number }).port;
  const old = await (await request.get("/api/llm/adapters")).json();
  const ids: string[] = [];
  try {
    await page
      .getByRole("button", { name: "Open configuration", exact: true })
      .click();
    await page
      .locator(".configuration-modal")
      .getByRole("button", { name: "AI Models", exact: true })
      .click();
    await page.getByLabel("LLM name", { exact: true }).fill("Test function A");
    await page
      .getByLabel("LLM base_url", { exact: true })
      .fill(`http://127.0.0.1:${port}/v1`);
    await page.getByLabel("LLM model", { exact: true }).fill("model-a");
    await expect(page.getByLabel("LLM default system prompt", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("LLM test system prompt", { exact: true })).toHaveCount(0);
    await page
      .getByRole("button", { name: "Save AI model", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Test model", exact: true }),
    ).toBeVisible();
    ids.push(
      ...(await (await request.get("/api/llm/adapters")).json()).adapters
        .filter((p: any) => !old.adapters.some((o: any) => o.id === p.id))
        .map((p: any) => p.id),
    );
    await page
      .getByRole("button", { name: "Test model", exact: true })
      .click();
    await expect(
      page.getByLabel("LLM test answer", { exact: true }),
    ).toHaveText("A recorded LLM answer");
    const second = await (
      await request.post("/api/llm/adapters", {
        data: {
          name: "Test function B",
          base_url: `http://127.0.0.1:${port}/v1`,
          model: "model-b",
        },
      })
    ).json();
    ids.push(second.id);
    await page
      .locator(".configuration-modal")
      .evaluate((el) => (el.scrollTop = 0));
    await page.screenshot({ path: "artifacts/global-llm-configuration.png" });
    await page
      .getByRole("button", { name: "Close configuration", exact: true })
      .click();
    await page.reload();
    await newPlan(page, "LLM plan");
    // Standalone answer tasks are a legacy project feature. Load a saved record;
    // the normal Add task button now creates a semantic robot task for the Converter.
    const pid=await page.getByLabel("Select project",{exact:true}).inputValue();
    const detail=await(await request.get(`/api/projects/${pid}`)).json();
    const definition=detail.plan_definitions.find((d:any)=>d.name==="LLM plan");
    const imported=await request.put(`/api/projects/${pid}/plan-definitions/${definition.id}`,{data:{name:definition.name,goal:definition.goal,version:definition.version,tasks:[{id:"legacy_llm",name:"New task",operation:"llm",robot_id:"",llm_input:"Analyze the environment",binding_status:"legacy"}]}});
    expect(imported.ok(),await imported.text()).toBeTruthy();
    await page.reload();
    await page.getByRole("dialog",{name:"Hello.",exact:true}).getByRole("button",{name:"Continue",exact:true}).click();
    await expect(page.getByRole("dialog",{name:"Hello.",exact:true})).toHaveCount(0);
    await expect(page.getByLabel("Task robot", { exact: true })).toHaveCount(0);
    await page
      .getByLabel("Task LLM adapter", { exact: true })
      .selectOption(second.id);
    await page
      .getByLabel("Task LLM input", { exact: true })
      .fill("Analyze the environment");
    await expect(page.getByLabel("Task LLM system prompt", { exact: true })).toHaveCount(0);
    await page
      .getByLabel("Task refinement instruction", { exact: true })
      .fill("Improve the task name");
    await expect(page.getByLabel("Task refinement instruction",{exact:true})).toHaveValue("Improve the task name");
    await expect(page.getByRole("button",{name:"Draft task refinement",exact:true})).toBeEnabled();
    await page
      .getByRole("button", { name: "Draft task refinement", exact: true })
      .click();
    await expect(page.getByLabel("Task name", { exact: true })).toHaveValue(
      "Refined LLM task",
    );
    await page
      .getByRole("button", { name: "Validate plan", exact: true })
      .click();
    await expect(
      page.getByText("Ready for simulation", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Run simulation", exact: true }).click();
    await expect(page.locator(".llm-results")).toContainText(
      "A recorded LLM answer",
    );
    await expect(page.locator(".run-status")).toHaveText("simulation passed");
    expect(calls.at(-1).model).toBe("model-b");
    expect(calls.at(-1).messages).toEqual([
      { role: "user", content: "Analyze the environment" },
    ]);
    await page.getByRole("tab", { name: "Run history", exact: true }).click();
    await expect(page.locator(".evidence")).toContainText(
      "A recorded LLM answer",
    );
  } finally {
    for (const id of ids) await request.delete(`/api/llm/adapters/${id}`);
    await request.put("/api/llm/default", {
      data: { adapter_id: old.default_id },
    });
    await new Promise<void>((r) => server.close(() => r()));
  }
});

test("robot reach is visible per instance and in simulation without changing task assignments", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await newPlan(page, "Workspace plan");
  await page.getByRole("button", { name: "Add task", exact: true }).click();
  const taskRobot = await page
    .getByLabel("Task robot", { exact: true })
    .inputValue();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Saved", exact: true }),
  ).toBeVisible();
  const project = created.at(-1)!;
  const before = await (await request.get(`/api/projects/${project}`)).json();
  const mutations: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/") && r.method() !== "GET")
      mutations.push(r.method() + " " + r.url());
  });
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Show robot workspace", exact: true })
    .click();
  await expect(page.locator('[data-workspace-robot="arm_01"]')).toHaveAttribute(
    "data-workspace-available",
    "true",
  );
  await page
    .getByLabel("Workspace robot", { exact: true })
    .selectOption("arm_02");
  await expect(page.locator('[data-workspace-robot="arm_02"]')).toHaveAttribute(
    "data-workspace-available",
    "true",
  );
  await expect(page.locator('[data-workspace-robot="arm_01"]')).toHaveCount(0);
  await page.getByLabel("Workspace robot", { exact: true }).selectOption("all");
  await expect(page.locator('[data-workspace-available="true"]')).toHaveCount(
    before.robots.length,
  );
  await page
    .getByRole("button", { name: "Fit robot workspace", exact: true })
    .click();
  await page.screenshot({ path: "artifacts/robot-reachable-workspaces.png" });
  await page
    .getByLabel("Workspace robot", { exact: true })
    .selectOption("arm_01");
  await expect(page.locator('[data-workspace-available="true"]')).toHaveCount(
    1,
  );
  await page
    .getByRole("button", { name: "Fit robot workspace", exact: true })
    .click();
  await page.screenshot({ path: "artifacts/robot-reachable-workspace.png" });
  await page
    .getByRole("button", { name: "Hide robot workspace", exact: true })
    .click();
  await expect(page.locator("[data-workspace-robot]")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Plans workspace", exact: true })
    .click();
  await expect(page.getByLabel("Task robot", { exact: true })).toHaveValue(
    taskRobot,
  );
  await page.getByRole("tab", { name: "Simulation", exact: true }).click();
  await page
    .getByRole("button", { name: "Show robot workspace", exact: true })
    .click();
  await expect(page.locator('[data-workspace-robot="arm_01"]')).toHaveAttribute(
    "data-workspace-available",
    "true",
  );
  const after = await (await request.get(`/api/projects/${project}`)).json();
  expect(after.robots.map((r: any) => r.state.positions)).toEqual(
    before.robots.map((r: any) => r.state.positions),
  );
  expect(after.fingerprint).toBe(before.fingerprint);
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
});

test("virtual custom commands accept parameters and cancel beside the built-in simulator", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Robots workspace", exact: true })
    .click();
  await openGlobalAdapterWizard(page);
  await page.getByRole("button", { name: /Virtual robot/ }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: /Define custom commands/ }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(
    page.getByLabel("Adapter interface", { exact: true }),
  ).toHaveValue("mock");
  await page
    .getByLabel("Adapter name", { exact: true })
    .fill("Parameterized custom adapter");
  await page
    .getByRole("button", { name: "Add custom command", exact: true })
    .click();
  const editor = page.locator(".command-definition").nth(1);
  await editor.locator("summary").click();
  await page.getByLabel("Command 2 ID", { exact: true }).fill("rotate");
  await page.getByLabel("Command 2 name", { exact: true }).fill("Rotate");
  await editor
    .getByRole("button", { name: "Add parameter", exact: true })
    .click();
  await page
    .getByLabel("Command 2 parameter 1 name", { exact: true })
    .fill("angle");
  await page
    .getByLabel("Command 2 parameter 1 default", { exact: true })
    .fill(".1");
  await page
    .getByLabel("Command 2 step 1 operation", { exact: true })
    .selectOption("move");
  await page
    .getByLabel("Command 2 step 1 value 1", { exact: true })
    .fill("$angle");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(page.locator(".review-command-list")).toContainText("Rotate");
  await page
    .getByLabel("I reviewed the generated adapter", { exact: true })
    .check();
  await page
    .getByRole("button", {
      name: "Record review & open simulator",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("button", { name: "Test Wave", exact: true }),
  ).toBeEnabled();
  await page
    .locator(".command-catalog")
    .getByRole("button")
    .filter({ hasText: "Rotate" })
    .click();
  await page.getByLabel("Test parameter angle", { exact: true }).fill(".2");
  await page.getByRole("button", { name: "Test Rotate", exact: true }).click();
  await expect(page.locator(".command-result")).toContainText(
    "rotate · passed",
  );
  await expect(
    page.getByLabel("Feedback base_yaw", { exact: true }),
  ).toContainText("0.2000");
  await page
    .locator(".command-catalog")
    .getByRole("button")
    .filter({ hasText: "Wave" })
    .click();
  await page.getByRole("button", { name: "Test Wave", exact: true }).click();
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(page.locator(".command-result")).toContainText(
    "wave · cancelled",
  );
  await expect(page.locator(".control-feedback")).toContainText(
    "Stopped: confirmed",
  );
  await page.getByRole("button", { name: "Done", exact: true }).click();
});

test("vendor documentation yields evidence-backed commands and unavailable actions remain explicit", async ({
  page,
  request,
}) => {
  const { createServer } = await import("node:http");
  const catalog = [
    {
      id: "move_base",
      name: "Move base",
      description: "Set the base angle.",
      vendor_command: "move_base(angle)",
      documentation_quote: "move_base(angle): set base angle in radians.",
      parameters: { angle: { min: -0.5, max: 0.5, default: 0, unit: "rad" } },
      steps: [
        { operation: "move", values: { base_yaw: "$angle" }, duration: 0.5 },
      ],
    },
    {
      id: "camera",
      name: "Capture image",
      simulation_supported: false,
      unsupported_reason: "Camera simulation is not configured.",
      steps: [],
    },
  ];
  const server = createServer(async (req, res) => {
    for await (const part of req) {
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        choices: [
          { message: { content: JSON.stringify({ commands: catalog }) } },
        ],
      }),
    );
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const port = (server.address() as { port: number }).port;
  const old = await (await request.get("/api/llm/adapters")).json();
  const profile = await (
    await request.post("/api/llm/adapters", {
      data: {
        name: "Documentation test provider",
        base_url: `http://127.0.0.1:${port}/v1`,
        model: "docs-model",
      },
    })
  ).json();
  try {
    await page
      .getByRole("button", { name: "Robots workspace", exact: true })
      .click();
    await openGlobalAdapterWizard(page);
    await page.getByRole("button", { name: /Virtual robot/ }).click();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page
      .getByRole("button", { name: /Use vendor documentation/ })
      .click();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page
      .getByLabel("Adapter name", { exact: true })
      .fill("Documented virtual adapter");
    await page.getByLabel("SDK version", { exact: true }).fill("1.0");
    await page
      .getByLabel("Documentation LLM adapter", { exact: true })
      .selectOption(profile.id);
    await page
      .getByLabel("SDK documentation", { exact: true })
      .fill(
        "move_base(angle): set base angle in radians. capture_image(): returns camera bytes.",
      );
    await page
      .getByRole("button", {
        name: "Extract commands from documentation",
        exact: true,
      })
      .click();
    await expect(page.locator(".command-definition")).toHaveCount(2);
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page
      .getByRole("button", { name: "Generate draft", exact: true })
      .click();
    await expect(page.locator(".review-command-list")).toContainText(
      "Capture image",
    );
    await page
      .getByLabel("I reviewed the generated adapter", { exact: true })
      .check();
    await page
      .getByRole("button", {
        name: "Record review & open simulator",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("button", { name: "Test Move base", exact: true }),
    ).toBeEnabled();
    await page.getByLabel("Test parameter angle", { exact: true }).fill(".12");
    await page
      .getByRole("button", { name: "Test Move base", exact: true })
      .click();
    await expect(page.locator(".command-result")).toContainText(
      "move_base · passed",
    );
    await page
      .locator(".command-catalog")
      .getByRole("button")
      .filter({ hasText: "Capture image" })
      .click();
    await expect(page.locator(".command-tester")).toContainText(
      "Camera simulation is not configured.",
    );
    await expect(
      page.getByRole("button", { name: "Test Capture image", exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: "Disconnect controls", exact: true })
      .click();
    await page.getByRole("button", { name: "Done", exact: true }).click();
  } finally {
    for (const id of controlSessions.splice(0))
      await request.delete(`/api/controls/${id}`);
    await request.delete(`/api/llm/adapters/${profile.id}`);
    await request.put("/api/llm/default", {
      data: { adapter_id: old.default_id },
    });
    await new Promise<void>((r) => server.close(() => r()));
  }
});

test("standardized task controls retain explicit units and bypass pose IK for direct targets", async ({
  page,
}) => {
  await newPlan(page, "Direct component task");
  await page.getByRole("button", { name: "Add task", exact: true }).click();
  await page.getByLabel("Semantic task intent",{exact:true}).fill("Set elbow to -1.6 rad");
  await page.getByText("Add a command manually",{exact:true}).click();
  await page.getByLabel("Approved task function",{exact:true}).selectOption("set_elbow");
  await expect(page.locator(".call-form")).toContainText("rad");
  await page.getByLabel("Function value",{exact:true}).fill("-1.6");
  await page.getByRole("button",{name:"Add function call",exact:true}).click();
  await expect(page.locator(".resolved-calls")).toContainText('set_elbow(value=-1.6, unit="rad")');
  await page.getByRole("button", { name: "Validate plan", exact: true }).click();
  await expect(
    page.getByText("Ready for simulation", { exact: true }),
  ).toBeVisible();
  const pid=await page.getByLabel("Select project",{exact:true}).inputValue();
  const detail=await(await page.request.get(`/api/projects/${pid}`)).json();
  const definition=detail.plan_definitions.find((d:any)=>d.name==="Direct component task");
  const revision=await(await page.request.get(`/api/projects/${pid}/plans/${definition.latest_revision_id}`)).json();
  expect(revision.motion_manifest.tasks[0].normalized[0].kind).toBe("joint");
  await page.getByRole("button", { name: "Run simulation", exact: true }).click();
  await expect(page.locator(".run-status.success")).toHaveText(
    "simulation passed",
    { timeout: 15000 },
  );
});

test("GCP connection panel explains catalog loading and tests a saved endpoint", async ({
  page,
}) => {
  let saved: any = {
    url: "http://127.0.0.1:9100",
    has_token: false,
    load_scene: false,
    gcp_project: "",
    gcp_zone: "",
    gcp_instance: "",
  };
  await page.route("**/api/configuration/isaac", async (route) => {
    if (route.request().method() === "PUT") {
      const { token, ...data } = route.request().postDataJSON();
      saved = { ...data, has_token: !!token };
    }
    await route.fulfill({ json: saved });
  });
  await page.route("**/api/configuration/isaac/probe", (route) =>
    route.fulfill({
      json: {
        engine: "isaac_sim",
        simulator_version: "6.2.0",
        scene_loading: true,
      },
    }),
  );
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page.getByText("NVIDIA Isaac Sim setup", { exact: true }).click();
  await page.getByRole("button", { name: "GCP GPU VM", exact: false }).click();
  await page.getByLabel("GCP project", { exact: true }).fill("test-project");
  await page.getByLabel("GCP zone", { exact: true }).fill("test-zone");
  await page.getByLabel("GCP instance", { exact: true }).fill("test-vm");
  await page
    .getByLabel("Isaac worker token", { exact: true })
    .fill("simulated-test-token");
  await page
    .getByLabel("Load project robots on connect", { exact: true })
    .check();
  await expect(
    page
      .locator(".connection-example")
      .filter({ hasText: "gcloud compute ssh" }),
  ).toContainText(
    "gcloud compute ssh test-vm --project=test-project --zone=test-zone",
  );
  await page
    .getByRole("button", { name: "Save worker connection", exact: true })
    .click();
  await expect(
    page.getByText("Connection saved.", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Test saved connection", exact: true })
    .click();
  await expect(
    page.getByText("robot loading available", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Isaac worker token", { exact: true }),
  ).toHaveValue("");
});

test("environment robot preview selects joints and tools, reverts, and commits a starting point", async ({
  page,
  request,
}) => {
  await expect(page.getByLabel("Select project", { exact: true })).toHaveValue(
    /^e2e_workflow_/,
  );
  const projectId = await page
    .getByLabel("Select project", { exact: true })
    .inputValue();
  const before = await (await request.get(`/api/projects/${projectId}`)).json();
  const robot = before.robots[0],
    name = robot.instance.instance.name;
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  // Picking the on-scene label opens the same inspector as picking the mesh.
  await page
    .getByRole("button", { name: `Select robot ${name}`, exact: true })
    .click();
  const editor = page.getByRole("region", { name: "Robot virtual controls" });
  await expect(
    editor.getByText("Connected · simulated feedback", { exact: true }),
  ).toBeVisible();
  await editor
    .getByRole("button", { name: "Select elbow", exact: true })
    .click();
  await expect(
    editor.getByLabel("Preview actuator", { exact: true }),
  ).toHaveValue("elbow");
  await editor.getByLabel("Preview joint target", { exact: true }).fill("-1.7");
  await editor.getByRole("button", { name: "Move joint", exact: true }).click();
  await expect(editor.locator(".joint-value")).toContainText("-1.7000 rad");
  const untouched = await (
    await request.get(`/api/projects/${projectId}`)
  ).json();
  expect(untouched.state.positions).toEqual(before.state.positions);
  expect(untouched.instance).toEqual(before.instance);
  await editor.getByRole("tab", { name: "End effector", exact: true }).click();
  await expect(
    editor.getByLabel("Tool target X", { exact: true }),
  ).toBeVisible();
  await expect(
    editor.getByRole("button", { name: "Move tool", exact: true }),
  ).toBeEnabled();
  await editor.getByRole("button", { name: "Move tool", exact: true }).click();
  await expect(
    editor.getByText("Connected · simulated feedback", { exact: true }),
  ).toBeVisible();
  await expect(editor.getByRole("alert")).toHaveCount(0);
  await editor.getByRole("button", { name: "Revert", exact: true }).click();
  await expect(editor).toHaveCount(0);
  const reverted = await (
    await request.get(`/api/projects/${projectId}`)
  ).json();
  expect(reverted.fingerprint).toBe(before.fingerprint);
  await page.locator(".scene-robot-picker button").first().click();
  await expect(
    editor.getByText("Connected · simulated feedback", { exact: true }),
  ).toBeVisible();
  await editor.getByText("Base position & rotation", { exact: true }).click();
  await editor.getByLabel("Draft base x", { exact: true }).fill(".05");
  await editor.getByLabel("Draft base yaw", { exact: true }).fill(".1");
  await editor
    .getByRole("button", { name: "Increase joint", exact: true })
    .click();
  await expect(editor.locator(".joint-value")).toContainText("0.0500 rad");
  await editor
    .getByRole("button", { name: "Use as starting point", exact: true })
    .click();
  await expect(editor).toHaveCount(0);
  const applied = await (
    await request.get(`/api/projects/${projectId}`)
  ).json();
  expect(applied.instance.base_pose.x).toBe(0.05);
  expect(applied.instance.base_pose.yaw).toBe(0.1);
  expect(
    applied.instance.initial_configuration.actuator_positions.base_yaw,
  ).toBeCloseTo(0.05);
  expect(applied.state.positions.base_yaw).toBeCloseTo(0.05);
  expect(applied.fingerprint).not.toBe(before.fingerprint);
  expect(errors).toEqual([]);
});

test("robot mesh dragging relocates its draft and rotation mode exposes the yaw ring", async ({
  page,
  request,
}) => {
  const { PerspectiveCamera, Vector3 } = await import("three");
  await expect(page.getByLabel("Select project", { exact: true })).toHaveValue(
    /^e2e_workflow_/,
  );
  const id = await page
    .getByLabel("Select project", { exact: true })
    .inputValue();
  const before = await (await request.get(`/api/projects/${id}`)).json();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page.locator(".scene-robot-picker button").first().click();
  const editor = page.getByRole("region", { name: "Robot virtual controls" });
  await expect(
    editor.getByText("Connected · simulated feedback", { exact: true }),
  ).toBeVisible();
  await editor.getByText("Base position & rotation", { exact: true }).click();
  const canvas = page.locator(".environment-scene canvas");
  const bounds = (await canvas.boundingBox())!;
  const camera = new PerspectiveCamera(
    37,
    bounds.width / bounds.height,
    0.01,
    200,
  );
  camera.position.set(1.1, 1.1, 1.15);
  camera.lookAt(0, 0.2, 0);
  camera.updateMatrixWorld();
  const links = before.model.kinematics.links;
  const p = new Vector3(
    links.upper_arm * 0.55 * Math.cos(initial.shoulder),
    links.base_height + links.upper_arm * 0.55 * Math.sin(initial.shoulder),
    0,
  ).project(camera);
  const x = bounds.x + ((p.x + 1) * bounds.width) / 2,
    y = bounds.y + ((1 - p.y) * bounds.height) / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 65, y - 20, { steps: 12 });
  await page.mouse.up();
  await expect
    .poll(async () =>
      Math.abs(
        Number(
          await editor.getByLabel("Draft base x", { exact: true }).inputValue(),
        ),
      ),
    )
    .toBeGreaterThan(0.02);
  expect(
    (await (await request.get(`/api/projects/${id}`)).json()).instance
      .base_pose,
  ).toEqual(before.instance.base_pose);
  await page.getByRole("button", { name: "↻ Rotate R", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "↻ Rotate R", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".scene-interaction-hint")).toContainText(
    "rotation ring",
  );
  // Hit the monitored yaw ring on the ground plane and drag around it.
  const base = {
    x: Number(
      await editor.getByLabel("Draft base x", { exact: true }).inputValue(),
    ),
    y: Number(
      await editor.getByLabel("Draft base y", { exact: true }).inputValue(),
    ),
    z: Number(
      await editor.getByLabel("Draft base z", { exact: true }).inputValue(),
    ),
  };
  const center = new Vector3(base.x, base.z, -base.y);
  const radius =
    (camera.position.distanceTo(center) *
      1.9 *
      Math.tan((Math.PI * 37) / 360) *
      1.5) /
    7;
  const theta =
    Math.atan2(camera.position.z - center.z, camera.position.x - center.x) -
    0.65;
  const ring = (a: number) => {
    const v = center
      .clone()
      .add(new Vector3(radius * Math.cos(a), 0, radius * Math.sin(a)))
      .project(camera);
    return {
      x: bounds.x + ((v.x + 1) * bounds.width) / 2,
      y: bounds.y + ((1 - v.y) * bounds.height) / 2,
    };
  };
  const start = ring(theta),
    end = ring(theta + 0.65);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 15 });
  await page.mouse.up();
  await expect
    .poll(async () =>
      Math.abs(
        Number(
          await editor
            .getByLabel("Draft base yaw", { exact: true })
            .inputValue(),
        ),
      ),
    )
    .toBeGreaterThan(0.1);
  await editor.getByRole("button", { name: "Revert", exact: true }).click();
  await expect(editor).toHaveCount(0);
  expect(
    (await (await request.get(`/api/projects/${id}`)).json()).state.positions,
  ).toEqual(before.state.positions);
});

test("first pointer drag selects and relocates a robot without a camera jump", async ({
  page,
  request,
}) => {
  const { PerspectiveCamera, Vector3 } = await import("three");
  await expect(page.getByLabel("Select project", { exact: true })).toHaveValue(
    /^e2e_workflow_/,
  );
  const id = await page
    .getByLabel("Select project", { exact: true })
    .inputValue();
  const before = await (await request.get(`/api/projects/${id}`)).json();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await expect(
    page.locator(".environment-scene .scene-robot-label").first(),
  ).toBeVisible();
  await page
    .locator(".environment-workspace")
    .evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
  const canvas = page.locator(".environment-scene canvas"),
    bounds = (await canvas.boundingBox())!;
  const camera = new PerspectiveCamera(
    37,
    bounds.width / bounds.height,
    0.01,
    200,
  );
  camera.position.set(1.7, 1.45, 1.2);
  camera.lookAt(0.15, 0.18, -0.65);
  camera.updateMatrixWorld();
  const links = before.model.kinematics.links;
  const p = new Vector3(
    links.upper_arm * 0.6 * Math.cos(initial.shoulder),
    links.base_height + links.upper_arm * 0.6 * Math.sin(initial.shoulder),
    0,
  ).project(camera);
  const x = bounds.x + ((p.x + 1) * bounds.width) / 2,
    y = bounds.y + ((1 - p.y) * bounds.height) / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 60, y - 12, { steps: 15 });
  await page.mouse.up();
  const editor = page.getByRole("region", { name: "Robot virtual controls" });
  await expect(editor).toBeVisible();
  await expect(
    editor.getByText("Connected · simulated feedback", { exact: true }),
  ).toBeVisible();
  await editor.getByText("Base position & rotation", { exact: true }).click();
  const dx = Math.abs(
    Number(
      await editor.getByLabel("Draft base x", { exact: true }).inputValue(),
    ),
  );
  const dy = Math.abs(
    Number(
      await editor.getByLabel("Draft base y", { exact: true }).inputValue(),
    ),
  );
  expect(dx).toBeGreaterThan(0.02);
  expect(dx).toBeLessThan(0.5);
  expect(dy).toBeLessThan(0.5);
  await editor.getByRole("button", { name: "Revert", exact: true }).click();
  const after = await (await request.get(`/api/projects/${id}`)).json();
  expect(after.instance).toEqual(before.instance);
  expect(after.state.positions).toEqual(before.state.positions);
});

test("adapter feedback moves the environment draft as well as the robot inspector", async ({
  page,
  request,
}) => {
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await page.locator(".scene-robot-picker button").first().click();
  const editor = page.getByRole("region", { name: "Robot virtual controls" });
  await expect(
    editor.getByText("Connected · simulated feedback", { exact: true }),
  ).toBeVisible();
  const canvas = page.locator(".environment-scene canvas");
  const before = await canvas.screenshot();
  const sid = controlSessions.at(-1)!;
  // Model delayed/independent adapter feedback, rather than a local optimistic update.
  const result = await request.post(`/api/controls/${sid}/standard-command`, {
    data: { type: "SET_ACTUATOR", target: "base_yaw", value: 0.7, unit: "rad" },
  });
  expect(result.ok()).toBeTruthy();
  await expect(editor.locator(".joint-value")).toContainText("0.7000 rad");
  expect(await canvas.screenshot()).not.toEqual(before);
  await editor.getByRole("button", { name: "Revert", exact: true }).click();
});

test("connected simulator movement is visible before closing its controls", async ({
  page,
  request,
}) => {
  await expect(page.getByLabel("Select project", { exact: true })).toHaveValue(
    /^e2e_workflow_/,
  );
  const id = await page
    .getByLabel("Select project", { exact: true })
    .inputValue();
  // Exercise native-control UI with the contract simulator: no GPU or hardware.
  await page.route(`**/api/projects/${id}`, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const detail = await response.json();
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
    const data = route.request().postDataJSON();
    await route.continue({
      postData: JSON.stringify({ ...data, adapter_id: "mock" }),
    });
  });
  await page.reload();
  await page
    .getByRole("button", { name: "Environment workspace", exact: true })
    .click();
  await expect(
    page.getByLabel("Simulation backend", { exact: true }),
  ).toHaveValue("isaac_sim");
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
  const canvas = page.locator(".environment-scene canvas");
  const before = await canvas.screenshot();
  await controls.getByLabel("Control base_yaw", { exact: true }).fill("1.2");
  await controls
    .getByRole("button", { name: "Send joint setpoints", exact: true })
    .click();
  await expect(
    controls.getByLabel("Feedback base_yaw", { exact: true }),
  ).toContainText("1.2000");
  // The main environment must update while the connection is still open.
  await expect(
    controls.getByRole("button", { name: "Disconnect controls", exact: true }),
  ).toBeVisible();
  await expect
    .poll(async () => !(await canvas.screenshot()).equals(before))
    .toBe(true);
  const measured = await (await request.get(`/api/projects/${id}`)).json();
  expect(measured.state.positions.base_yaw).toBeCloseTo(1.2);
  await controls
    .getByRole("button", { name: "Disconnect controls", exact: true })
    .click();
});

test("LLM code setup accepts a standard function without exposing prompt fields", async ({ page, request }) => {
  const old = await (await request.get('/api/llm/adapters')).json();
  let id: string | undefined;
  try {
    await page.getByRole('button', {name:'Open configuration',exact:true}).click();
    await page.getByRole('button', {name:'AI Models',exact:true}).click();
    await page.getByLabel('Custom Python function',{exact:true}).check();
    await expect(page.locator('.llm-code-setup .monaco-editor')).toBeVisible();
    await page.getByLabel('LLM name',{exact:true}).fill('Standard function test');
    await page.getByLabel('LLM model',{exact:true}).fill('custom-test');
    await page.getByLabel('Import LLM adapter code',{exact:true}).setInputFiles({name:'adapter.py',mimeType:'text/x-python',buffer:Buffer.from('async def invoke(input: str, system_prompt: str) -> str:\n    return "Function received: " + input\n')});
    await page.getByRole('button',{name:'Save AI model',exact:true}).click();
    await expect(page.getByText('AI model saved. Recompile affected plans.',{exact:true})).toBeVisible();
    const saved = await (await request.get('/api/llm/adapters')).json();
    id = saved.adapters.find((a:any)=>a.name==='Standard function test').id;
    expect(saved.adapters.find((a:any)=>a.id===id)).not.toHaveProperty('system_prompt');
    await expect(page.locator('textarea[aria-label*="system prompt"]')).toHaveCount(0);
    await page.getByLabel('LLM test input',{exact:true}).fill('sample input');
    await page.getByRole('button',{name:'Test model',exact:true}).click();
    await expect(page.getByLabel('LLM test answer',{exact:true})).toHaveText('Function received: sample input');
    await page.getByLabel('OpenAI-compatible API',{exact:true}).check();
    await expect(page.locator('.llm-code-setup')).toHaveCount(0);
  } finally {
    if(id) await request.delete(`/api/llm/adapters/${id}`);
    await request.put('/api/llm/default',{data:{adapter_id:old.default_id}});
  }
});

test('RoboDE wordmark aligns beside its logo and project IDs are discoverable', async ({page}) => {
  await expect(page.getByLabel('Project ID',{exact:true})).not.toHaveValue('');
  for (const width of [1100,1280,1600]) {
    await page.setViewportSize({width,height:900});
    const mark = await page.locator('.titlebar .brand-mark').boundingBox();
    const word = await page.locator('.titlebar .brand strong').boundingBox();
    expect(word!.x).toBeGreaterThanOrEqual(mark!.x+mark!.width+8);
    expect(Math.abs(word!.y+word!.height/2-mark!.y-mark!.height/2)).toBeLessThan(3);
    await expect(page.locator('.titlebar .brand strong')).toHaveText('RoboDE');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
});
