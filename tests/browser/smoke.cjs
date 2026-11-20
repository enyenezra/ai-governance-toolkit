const assert = require("node:assert/strict");
const axe = require("axe-core");
const { chromium } = require("playwright-core");

async function assertAccessible(page) {
  await page.evaluate(axe.source);
  const result = await page.evaluate(() => window.axe.run({
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
  }));
  assert.deepEqual(result.violations.map((item) => ({ rule: item.id, targets: item.nodes.map((node) => node.target) })), []);
}

async function main() {
  const browser = await chromium.launch({
    executablePath: process.env.AIGOVKIT_CHROMIUM,
    headless: true,
  });
  try {
    const base = process.env.AIGOVKIT_BROWSER_URL;
    const apiKey = process.env.AIGOVKIT_BROWSER_EDITOR;
    const readerKey = process.env.AIGOVKIT_BROWSER_READER;
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(base + "/workspace");
    await page.getByRole("heading", { name: "Sign in to AIGovKit" }).waitFor();
    await assertAccessible(page);

    async function login(key) {
      await page.getByLabel("Organisation API key").fill(key);
      await page.getByRole("button", { name: "Open workspace" }).click();
      await page.getByRole("button", { name: "Sign out" }).waitFor();
    }

    await login(apiKey);
    await page.getByRole("link", { name: "Organisation setup" }).click();
    await page.getByLabel("Organisation name").fill("Browser smoke tenant");
    await page.getByLabel("Sector").fill("Technology");
    await page.getByLabel("Jurisdiction").fill("UK");
    await page.getByRole("button", { name: "Save organisation" }).click();
    await page.getByText("Organisation saved.").waitFor();

    await page.getByRole("link", { name: "Provider enforcement" }).click();
    await page.getByRole("heading", { name: "Register a provider" }).waitFor();
    const providerForm = page.locator("#provider-form");
    await providerForm.getByLabel("Provider ID", {exact: true}).fill("browser-provider");
    await providerForm.getByLabel("Name", {exact: true}).fill("Browser fixture provider");
    await providerForm.getByLabel("HTTPS endpoint").fill("https://provider.example.invalid");
    await page.getByRole("button", { name: "Register provider" }).click();
    await page.getByText("Provider registered.").waitFor();
    await page.getByRole("cell", { name: "Browser fixture provider" }).waitFor();
    await assertAccessible(page);

    await page.getByRole("link", { name: "Security findings" }).click();
    await page.getByRole("button", { name: "Run detections" }).click();
    await page.getByText("0 new findings · 0 new incidents.").waitFor();
    await assertAccessible(page);

    await page.getByRole("link", { name: "Connected discovery" }).click();
    await page.getByRole("heading", { name: "Google Workspace" }).waitFor();
    await assertAccessible(page);
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("heading", { name: "Sign in to AIGovKit" }).waitFor();

    await login(readerKey);
    await page.getByRole("link", { name: "Organisation setup" }).click();
    await page.getByText(/Browser smoke tenant/).waitFor();
    assert.equal(await page.getByRole("button", { name: "Save organisation" }).isVisible(), false);
    const rejected = await page.request.put(base + "/v1/organisation", {
      headers: { "X-API-Key": readerKey },
      data: { name: "Unauthorised", sector: "Technology", jurisdiction: "UK", adoption_stage: "piloting" },
    });
    assert.equal(rejected.status(), 403);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("link", { name: "Devices", exact: true }).click();
    await page.getByText("No devices observed.").waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
    await assertAccessible(page);
    console.log("Browser accessibility and role checks passed.");
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
