import { afterEach, it, expect, vi } from "vitest";
import { installBackendFetchPolicy, trackPath } from "../src/renderer";

afterEach(() => vi.unstubAllGlobals());

it("uses the pinned renderer's UUID track interface instead of legacy catalogue triggers", () => {
  expect(trackPath("238393ed-0f93-45ae-a91e-491b1c3a0b40")).toEqual(["track", "expand", "238393ed-0f93-45ae-a91e-491b1c3a0b40"]);
});

it("omits credentials for both priorities, preserves POST data, and restores fetch", async () => {
  const original = vi.fn().mockResolvedValue(new Response("ok"));
  const scope = { fetch: original, location: { href: "https://sandbox.invalid/app" } };
  vi.stubGlobal("window", scope);
  const failure = vi.fn();
  const restore = installBackendFetchPolicy("https://data.invalid/api/browser/data", failure);
  for (const priority of ["hi", "lo"]) {
    const request = new Request(`https://data.invalid/api/browser/data/${priority}?stamp=1`, { method: "POST", body: new Uint8Array([1, 2]), credentials: "include" });
    await scope.fetch(request);
    expect(original).toHaveBeenLastCalledWith(request, { credentials: "omit", mode: "cors" });
    expect(request.method).toBe("POST");
  }
  await scope.fetch("https://other.invalid/file");
  expect(original).toHaveBeenLastCalledWith("https://other.invalid/file", undefined);
  expect(failure).not.toHaveBeenCalled();
  restore(); expect(scope.fetch).toBe(original);
});

it("reports network and HTTP failures without hiding them", async () => {
  const original = vi.fn().mockResolvedValueOnce(new Response("", { status: 503 })).mockRejectedValueOnce(new TypeError("Network failure"));
  const scope = { fetch: original, location: { href: "https://sandbox.invalid/app" } };
  vi.stubGlobal("window", scope);
  const failure = vi.fn();
  installBackendFetchPolicy("https://data.invalid/data", failure);
  expect((await scope.fetch("https://data.invalid/data/hi")).status).toBe(503);
  await expect(scope.fetch("https://data.invalid/data/lo")).rejects.toThrow("Network failure");
  expect(failure).toHaveBeenCalledTimes(2);
});
