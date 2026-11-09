import { test, expect } from "@playwright/test";

test("navigates locally and sends selection context only for clicks", async ({ page }) => {
  await page.goto("/");
  const app = page.frameLocator("#app");
  await expect(app.locator("#status")).toContainText("Tracks loaded");
  await expect(app.locator("#identity")).toContainText("GCA_000001405.29");
  await app.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(app.locator("#location")).not.toHaveText("13:32,315,086-32,400,268");
  expect(await page.evaluate(() => (window as any).calls.filter((call: any) => call.method === "ui/update-model-context").length)).toBe(0);
  await app.getByRole("button", { name: "Mock gene selection" }).click();
  await expect(app.locator("#selection")).toContainText("ENSG00000012048.24");
  await app.getByRole("button", { name: "Explain this selection" }).click();
  await expect.poll(() => page.evaluate(() => (window as any).calls.filter((call: any) => call.method === "ui/message").length)).toBe(1);
  const message = await page.evaluate(() => (window as any).calls.find((call: any) => call.method === "ui/message"));
  expect(message.params.content[0].text).toContain("59871324-7803-4234-856e-2a2bd96d7b3c");
  expect(message.params.content[0].text).toContain("ENSG00000012048.24");
  await app.getByRole("button", { name: "Reset view" }).click();
  await expect(app.locator("#location")).toHaveText("13:32,315,086-32,400,268");
  await app.getByRole("button", { name: "Larger view" }).click();
  await expect(app.locator("body")).toHaveClass("fullscreen");
});

test("requires a choice for ambiguous genes and handles empty results", async ({ page }) => {
  await page.goto("/"); const app = page.frameLocator("#app");
  await expect(app.locator("#status")).toContainText("Tracks loaded");
  await app.getByLabel("Go to gene").fill("DUP"); await app.getByRole("button", { name: "Find", exact: true }).click();
  await expect(app.getByLabel("Choose a gene match")).toBeVisible();
  expect(await page.evaluate(() => (window as any).calls.filter((c: any) => c.method === "tools/call" && c.params.name === "show_genome_browser").length)).toBe(0);
  await app.getByLabel("Choose a gene match").selectOption("ENSG2.1");
  await expect.poll(() => page.evaluate(() => (window as any).calls.filter((c: any) => c.method === "tools/call" && c.params.name === "show_genome_browser").length)).toBe(1);
  await app.getByLabel("Go to gene").fill("ABSENT"); await app.getByRole("button", { name: "Find", exact: true }).click();
  await expect(app.locator("#status")).toContainText("No matching genes");
});

test("retains the view on unrelated results and reports missing catalogue", async ({ page }) => {
  await page.goto("/"); const app = page.frameLocator("#app");
  await expect(app.locator("#status")).toContainText("Tracks loaded");
  await page.evaluate(() => (window as any).sendResult({ structuredContent: { gene: { symbol: "BRCA2" } }, content: [] }));
  await expect(app.locator("#location")).toHaveText("13:32,315,086-32,400,268");
  await page.evaluate(() => (window as any).sendResult({ ...(window as any).result, _meta: {} }));
  await expect(app.locator("#status")).toContainText("did not supply");
  await page.reload();
  await expect(app.locator("#status")).toContainText("Tracks loaded");
  await expect(app.locator("#location")).toHaveText("13:32,315,086-32,400,268");
});
