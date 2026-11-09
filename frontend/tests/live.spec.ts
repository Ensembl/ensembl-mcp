import { test, expect } from "@playwright/test";
import { writeFile } from "node:fs/promises";

// Explicitly opt-in: network-backed renderer checks are never an offline-test result.
test.skip(process.env.MCP_BROWSER_LIVE !== "1", "Set MCP_BROWSER_LIVE=1 after producing live fixtures");
for (const locus of ["brca2", "demo"]) {
  test(`real renderer displays ${locus} in a local sandbox`, async ({ page }, testInfo) => {
    test.setTimeout(90000);
    const responses: { path: string; status: number; type: string }[] = [];
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => {
      if (response.url().includes("/api/browser/data/")) responses.push({ path: new URL(response.url()).pathname, status: response.status(), type: response.headers()["content-type"] ?? "" });
    });
    // Observe the actual fetch options at the browser boundary. This wraps the
    // native fetch before the app installs its own credential policy.
    await page.addInitScript(() => {
      const original = window.fetch;
      (window as any).backendRequests = [];
      window.fetch = (input, init) => {
        const url = input instanceof Request ? input.url : String(input);
        if (url.includes("/api/browser/data/")) (window as any).backendRequests.push({ url, credentials: init?.credentials });
        return original(input, init);
      };
    });
    await page.goto(`/?live=${locus}`);
    const app = page.frameLocator("#app");
    await expect(app.locator("#status")).toContainText("Tracks loaded", { timeout: 60000 });
    await expect(app.locator("canvas").first()).toBeVisible();
    const initialLocation = await app.locator("#location").textContent();
    await app.getByRole("button", { name: "Zoom in", exact: true }).click();
    // Wait for animated navigation before starting the next navigation.
    let previous = ""; let stable = 0;
    await expect.poll(async () => {
      const location = await app.locator("#location").textContent() ?? "";
      stable = location === previous && location !== initialLocation ? stable + 1 : 0;
      previous = location; return stable;
    }, { intervals: [200], timeout: 10000 }).toBeGreaterThanOrEqual(3);
    await app.getByRole("button", { name: "Pan right", exact: true }).click();
    stable = 0;
    await expect.poll(async () => {
      const location = await app.locator("#location").textContent() ?? "";
      stable = location === previous ? stable + 1 : 0; previous = location; return stable;
    }, { intervals: [200], timeout: 10000 }).toBeGreaterThanOrEqual(3);
    await expect.poll(() => responses.some(response => response.path.endsWith("/hi") && response.status === 200)).toBeTruthy();
    await expect.poll(() => responses.some(response => response.path.endsWith("/lo") && response.status === 200)).toBeTruthy();
    const requests = await page.frames().find(frame => frame.url().endsWith("/real"))!.evaluate(() => (window as any).backendRequests);
    expect(requests.length).toBeGreaterThan(0);
    expect(requests.every((request: any) => request.credentials === "omit")).toBeTruthy();
    expect(errors).toEqual([]);
    if (locus === "demo") {
      // At this settled zoom/pan ICAM2 occupies the left of the reverse-strand row.
      await app.locator("canvas").first().click({ position: { x: 100, y: 324 } });
      await expect(app.locator("#selection")).toContainText("Selected gene:");
      await app.getByRole("button", { name: "Explain this selection" }).click();
      await expect.poll(() => page.evaluate(() => (window as any).calls.some((call: any) => call.method === "ui/message"))).toBeTruthy();
    }
    await page.screenshot({ path: testInfo.outputPath(`${locus}.png`), fullPage: true });
    const evidence = JSON.stringify({ responses, requests, errors, browser: page.context().browser()?.version() }, null, 2);
    await writeFile(testInfo.outputPath("network.json"), evidence);
    await testInfo.attach("network", { body: evidence, contentType: "application/json" });
  });
}
