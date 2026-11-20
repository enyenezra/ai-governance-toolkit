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
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto(base);
    await page.getByRole("heading", { name: "Risk assessment", exact: true }).waitFor();
    await assertAccessible(page);
    await page.getByLabel("Likelihood").selectOption("4");
    await page.getByLabel("Impact").selectOption("5");
    await page.getByLabel("Uses personal data").check();
    await page.route("**/assessments", (route) => route.fulfill({ status: 503 }), { times: 1 });
    await page.getByRole("button", { name: "Assess risk" }).click();
    await page.getByRole("alert").waitFor();
    await page.getByRole("button", { name: "Assess risk" }).click();
    await page.getByText("20 / 25 · high risk").waitFor();
    await page.getByText("Human review required").waitFor();
    await assertAccessible(page);
    await page.getByRole("link", { name: "Governance workspace" }).click();
    await page.getByRole("heading", { name: "Sign in to AIGovKit" }).waitFor();
    const pageIds = await page.locator("#workspace-root .page").evaluateAll(
      (sections) => sections.map((section) => section.id).sort(),
    );
    const navigationIds = await page.locator("#workspace-root nav a").evaluateAll(
      (links) => links.map((link) => link.hash.slice(1)).sort(),
    );
    assert.deepEqual(pageIds, navigationIds);
    assert.equal(pageIds.length, 21);
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

    const today = new Date().toISOString().slice(0, 10);
    await page.getByRole("link", { name: "Executive reports" }).click();
    await page.getByLabel("Period start").fill(today);
    await page.getByLabel("Period end").fill(today);
    await page.getByRole("button", { name: "Generate report" }).click();
    await page.getByText("0 assessments · 0 high risk").waitFor();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download PDF" }).click();
    assert.match((await download).suggestedFilename(), /^aigovkit-.*\.pdf$/);
    await assertAccessible(page);

    await page.getByRole("link", { name: "Training courses" }).click();
    await page.locator("#learning-course-select").selectOption("responsible-use-v1");
    await page.getByLabel("Learner member ID").fill("reader");
    await page.getByLabel("Due date").fill(today);
    await page.getByRole("button", { name: "Assign training" }).click();
    await page.getByText(/reader · Due .* · assigned/).waitFor();
    const courseDraft = page.locator("#course-editor");
    await courseDraft.getByLabel("Course ID").fill("browser-course");
    await courseDraft.getByLabel("Course title").fill("Browser authored course");
    await courseDraft.getByLabel("Lesson text").fill("Use approved tools.");
    await courseDraft.getByLabel("Quiz question").fill("Which tools are approved?");
    await courseDraft.getByLabel("First choice").fill("Approved tools");
    await courseDraft.getByLabel("Second choice").fill("Any tool");
    await courseDraft.getByRole("button", { name: "Save course draft" }).click();
    await page.getByText("Course draft saved.").waitFor();
    await assertAccessible(page);

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

    await page.getByRole("link", { name: "Notifications", exact: true }).click();
    await page.getByText("Outbound delivery requires an operator-configured destination.").waitFor();
    await page.getByRole("button", { name: "Save notification preferences" }).click();
    await page.getByText("Notification preferences saved.").waitFor();
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

    await login(process.env.AIGOVKIT_BROWSER_PUBLISHER);
    await page.getByRole("link", { name: "Training courses" }).click();
    await page.getByRole("button", { name: "Publish course" }).click();
    await page.getByText("Course published.").waitFor();
    await assertAccessible(page);
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("heading", { name: "Sign in to AIGovKit" }).waitFor();

    await login(readerKey);
    assert.equal(await page.getByRole("link", { name: "Executive reports" }).isVisible(), false);
    await page.getByRole("link", { name: "Training courses" }).click();
    await page.getByRole("button", { name: "Verify the output against a trusted source" }).click();
    await page.getByText("Score 100%").waitFor();
    await assertAccessible(page);
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
    assert.deepEqual(pageErrors, []);
    console.log("Browser accessibility and role checks passed.");
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
