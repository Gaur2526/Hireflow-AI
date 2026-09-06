/**
 * End-to-end walk of the product in a real browser.
 * Drives the UI the way a recruiter would and screenshots each step.
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = "/Users/rahul.kumar/Desktop/assignment-project/docs/screenshots";
mkdirSync(OUT, { recursive: true });

const BASE = "http://localhost:3000";
const errors = [];
const step = async (page, name) => {
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(`  📸 ${name}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });

page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
});
page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
page.on("requestfailed", (req) => {
  if (!req.url().includes("favicon")) errors.push(`requestfailed: ${req.url()}`);
});

try {
  console.log("1. Dashboard");
  await page.goto(BASE, { waitUntil: "networkidle" });
  await step(page, "01-dashboard");

  console.log("2. New job");
  await page.goto(`${BASE}/jobs/new`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Use a sample" }).click();
  await page.getByLabel("Company").fill("Northwind Pay");
  await page.getByRole("button", { name: "Analyse" }).click();
  await page.getByText("Search criteria").waitFor({ timeout: 20000 });
  await step(page, "02-jd-analysed");

  console.log("3. Save job");
  await page.getByRole("button", { name: "Save job" }).click();
  await page.waitForURL(/\/jobs\/[0-9a-f-]{36}$/, { timeout: 20000 });
  const jobUrl = page.url();
  await page.waitForLoadState("networkidle");
  await step(page, "03-job-detail");

  console.log("4. Source candidates");
  await page.getByRole("button", { name: "Source candidates" }).first().click();
  await page.locator("table tbody tr").first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(900);
  const rows = await page.locator("table tbody tr").count();
  console.log(`   -> ${rows} candidates in the table`);
  await step(page, "04-candidates-sourced");

  console.log("5. Select top candidates");
  const boxes = page.locator('table tbody input[type="checkbox"], table tbody button[role="checkbox"]');
  const n = Math.min(3, await boxes.count());
  for (let i = 0; i < n; i += 1) await boxes.nth(i).click();
  await page.waitForTimeout(300);
  await step(page, "05-selected");

  console.log("6. Screening script tab");
  await page.getByRole("tab", { name: "Screening script" }).click();
  await page.waitForTimeout(900);
  await step(page, "06-screening-script");

  console.log("7. Criteria tab");
  await page.getByRole("tab", { name: "Criteria" }).click();
  await page.waitForTimeout(600);
  await step(page, "07-criteria");

  console.log("8. Launch dialog (dry run)");
  await page.getByRole("tab", { name: "Candidates" }).click();
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /Screen \d* ?by voice/ }).first().click();
  await page.getByText("Launch voice screening").waitFor({ timeout: 10000 });
  await page.waitForTimeout(500);
  await step(page, "08-launch-dialog");

  await page.getByLabel("Dry run").click().catch(async () => {
    await page.locator('button[role="checkbox"]').last().click();
  });
  await page.waitForTimeout(300);
  await page.getByRole("button", { name: /Create agent|Call \d+/ }).click();
  await page.waitForURL(/\/campaigns\/[0-9a-f-]{36}$/, { timeout: 45000 });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);
  console.log("9. Campaign dashboard");
  await step(page, "09-campaign-dashboard");

  console.log("10. Campaigns list");
  await page.goto(`${BASE}/campaigns`, { waitUntil: "networkidle" });
  await step(page, "10-campaigns");

  console.log("11. Settings");
  await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await step(page, "11-settings");

  console.log("12. Jobs list");
  await page.goto(`${BASE}/jobs`, { waitUntil: "networkidle" });
  await step(page, "12-jobs");

  console.log(`\nJob URL: ${jobUrl}`);
} catch (error) {
  console.error("\n❌ FAILED:", error.message);
  await page.screenshot({ path: `${OUT}/failure.png`, fullPage: true });
  errors.push(`flow: ${error.message}`);
} finally {
  await browser.close();
}

console.log(`\n${errors.length ? "⚠️  issues:" : "✅ no console/network errors"}`);
errors.slice(0, 25).forEach((e) => console.log("  -", e));
process.exit(errors.some((e) => e.startsWith("flow:")) ? 1 : 0);
