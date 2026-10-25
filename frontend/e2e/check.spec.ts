import { expect, test } from "@playwright/test";
import path from "node:path";

const fixtures = path.join(process.env.E2E_DATA || "/tmp/reel-checker-e2e", "fixtures");
// Next.js renders its own (empty) role="alert" route announcer, so match the form's alert by class.
const formAlert = (page: import("@playwright/test").Page) => page.locator("p.alert[role=alert]");

test("recycled footage: upload → progress → report → share → feedback", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Is this reel old footage?" })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(path.join(fixtures, "recycled.mp4"));
  await expect(page.getByText("recycled.mp4")).toBeVisible();
  await page.getByText("Add the caption and date").click();
  await page.getByLabel("Caption of the post").fill("Plane crash today at Hyderabad airport");
  await page.getByRole("button", { name: "Check this reel" }).click();

  // Progress page, then the report opens by itself.
  await expect(page).toHaveURL(/\/(check|r)\/[0-9a-f]{12}$/);
  await expect(page).toHaveURL(/\/r\/[0-9a-f]{12}$/, { timeout: 45_000 });

  await expect(page.getByRole("heading", { level: 1, name: "Likely old footage" })).toBeVisible();
  await expect(page.getByText("A plane crashed at Hyderabad airport today.")).toBeVisible();
  await expect(page.getByText(/YouTube on 2 March 2015/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Cargo plane crash caught on camera" })).toHaveAttribute(
    "href", "https://www.youtube.com/watch?v=OLD123");
  await expect(page.getByText(/frame match/).first()).toBeVisible();
  // The non-matching result is tucked away and never shown as a percentage.
  await expect(page.getByText("1 related result that don't match")).toBeVisible();

  const compare = page.getByRole("img", { name: /frame from the reel next to/ });
  await expect(compare).toBeVisible();
  expect(await compare.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(100);

  // Share links point at this page.
  const id = page.url().split("/r/")[1];
  const wa = page.getByRole("link", { name: "Share on WhatsApp" });
  await expect(wa).toHaveAttribute("href", new RegExp(`^https://wa\\.me/\\?text=.*Likely%20old%20footage.*%2Fr%2F${id}$`));

  // Preview tags for WhatsApp / Telegram.
  const html = await (await page.request.get(`/r/${id}`, { headers: { "User-Agent": "WhatsApp/2.24" } })).text();
  expect(html).toContain('<meta property="og:title" content="Reel check: Likely old footage"');
  expect(html).toMatch(/<meta property="og:image" content="http:\/\/localhost:8010\/api\/reports\/[0-9a-f]{12}\/files\/compare_1\.jpg"/);

  // Feedback reaches the backend.
  await page.getByRole("button", { name: "No, report a mistake" }).click();
  await page.getByLabel("What is wrong? (optional)").fill("e2e test");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Thank you.")).toBeVisible();
});

test("same file again is answered instantly from the cache", async ({ page }) => {
  for (let i = 0; i < 2; i++) {
    await page.goto("/");
    await page.locator('input[type="file"]').setInputFiles(path.join(fixtures, "fresh.mp4"));
    await page.getByRole("button", { name: "Check this reel" }).click();
    await expect(page).toHaveURL(/\/r\/[0-9a-f]{12}$/, { timeout: 45_000 });
  }
  // Scope to the report: Next keeps the previous page mounted but hidden (React <Activity>).
  const report = page.getByRole("article");
  await expect(report.getByRole("heading", { level: 1, name: "No contradiction found" })).toBeVisible();
  await expect(report.getByText("That is not proof the reel is real.").first()).toBeVisible();
});

test("rejects a non-video before uploading", async ({ page }) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hi") });
  await expect(formAlert(page)).toHaveText(/Choose a video file/);
  await expect(page.getByRole("button", { name: "Check this reel" })).toBeDisabled();
});

test("server-side rejection is shown to the user", async ({ page }) => {
  await page.goto("/");
  // Looks like a video to the browser, but ffprobe can't read it.
  await page.locator('input[type="file"]').setInputFiles({ name: "broken.mp4", mimeType: "video/mp4", buffer: Buffer.alloc(4000) });
  await page.getByRole("button", { name: "Check this reel" }).click();
  await expect(formAlert(page)).toHaveText(/Cannot analyse this file/);
});

test("unknown report and job ids", async ({ page }) => {
  // The streamed shell is already sent (200) when the lookup fails, so Next marks the page noindex instead of 404.
  await page.goto("/r/0123456789ab");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await expect(page.locator('meta[name="robots"][content*="noindex"]').first()).toBeAttached();
  await page.goto("/check/0123456789ab");
  await expect(page.getByRole("heading", { name: "Check not found" })).toBeVisible();
});

test("pages fit a phone screen without sideways scrolling", async ({ page }) => {
  for (const url of ["/", "/privacy"]) {
    await page.goto(url);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, url).toBeLessThanOrEqual(0);
  }
});
