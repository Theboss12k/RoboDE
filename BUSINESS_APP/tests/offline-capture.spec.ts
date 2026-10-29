import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
test("offline capture exports a portable ZIP which the IDE imports without changing its scene", async ({
  page,
  request,
}) => {
  await page.goto("/business/room-capture.html");
  await page.getByLabel("Room name").fill("Offline room QA");
  await page
    .locator("#choose")
    .setInputFiles({
      name: "photo.png",
      mimeType: "image/png",
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0FcAAAAASUVORK5CYII=",
        "base64",
      ),
    });
  await expect(page.getByRole("status")).toContainText("1 photos");
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export room capture (.zip)", exact: true })
    .click();
  const file = await pending;
  const data = await readFile((await file.path())!);
  const before = await (
    await request.get("http://127.0.0.1:8876/api/projects/apple_transfer")
  ).json();
  const imported = await request.post(
    "http://127.0.0.1:8876/api/business/projects/apple_transfer/rooms/import-capture",
    { data, headers: { "Content-Type": "application/zip" } },
  );
  expect(imported.status()).toBe(201);
  expect((await imported.json()).photos).toBe(1);
  const after = await (
    await request.get("http://127.0.0.1:8876/api/projects/apple_transfer")
  ).json();
  expect(after.objects).toEqual(before.objects);
  await page.reload();
  await expect(page.getByRole("status")).toContainText("1 photos");
});
