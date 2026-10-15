const assert = require("node:assert/strict");
const {spawn} = require("node:child_process");
const {once} = require("node:events");
const path = require("node:path");
const fs = require("node:fs/promises");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");

(async () => {
  const python = process.env.PYTHON || (process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
  const server = spawn(python, ["-m", "tests.public_browser_server"], {stdio: ["ignore", "pipe", "inherit"]});
  let browser;
  try {
    const [chunk] = await once(server.stdout, "data");
    const {port} = JSON.parse(chunk.toString().trim());
    const base = `http://127.0.0.1:${port}/products/schedula/`;
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage();
    const failures = [], requests = [];
    page.on("pageerror", error => failures.push(error.message));
    page.on("request", request => requests.push(request.url()));
    await page.goto(base + "demo/");
    await page.getByRole("link", {name: "必要人数に合わせる", exact: true}).waitFor();
    assert.equal(await page.locator("#feature-list a").count(), 3);
    for (const hash of ["json", "large", "records", "combined"]) {
      await page.goto(base + "demo/#" + hash);
      await page.locator("#feature-list [role=status]").filter({hasText: "準備中"}).waitFor();
      assert.equal(await page.locator('input[type="file"], textarea').count(), 0);
    }
    await page.goto(base + "demo/#demand");
    await page.locator("#feature-status").filter({hasText: "OPTIMAL"}).waitFor({timeout: 45000});
    await page.locator("#feature-number").fill("4");
    await page.getByRole("button", {name: "再計算", exact: true}).click();
    await page.locator("#feature-status").filter({hasText: "PARTIAL"}).waitFor({timeout: 45000});
    assert.match(await page.locator("#feature-output").innerText(), /60人分/);
    await page.goto(base + "demo/#consecutive_days");
    await page.locator("#feature-status").filter({hasText: "OPTIMAL"}).waitFor({timeout: 45000});
    await page.locator("#feature-number").fill("3");
    await page.getByRole("button", {name: "再計算", exact: true}).click();
    await page.locator("#feature-status").filter({hasText: "OPTIMAL"}).waitFor({timeout: 45000});
    await page.goto(base + "demo/#verify");
    await page.locator("#feature-status").filter({hasText: "VALID ·"}).waitFor({timeout: 45000});
    await page.locator("#feature-kitchen").selectOption("bob");
    await page.getByRole("button", {name: "再検証", exact: true}).click();
    await page.locator("#feature-status").filter({hasText: "INVALID_PLAN"}).waitFor({timeout: 45000});
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({width, height: 900});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
    }
    await page.goto(base + "docs/");
    await page.getByRole("link", {name: "公開APIとエラー処理（Markdown） ↗"}).waitFor();
    assert.deepEqual(failures, []);
    assert(requests.every(url => url.startsWith(base)), requests.filter(url => !url.startsWith(base)));
    const destination = path.resolve("test-results/public-demo");
    await fs.mkdir(destination, {recursive: true});
    await page.screenshot({path: path.join(destination, "guide.png"), fullPage: true});
    console.log("Public demo prefix, body hashes, three lessons, docs and mobile checks passed");
  } finally {
    if (browser) await browser.close();
    server.kill("SIGTERM");
    await once(server, "exit").catch(() => {});
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
