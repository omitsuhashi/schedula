// LPの主導線・文書・実デモの遷移を、外部への送信なしで確認する。
const assert = require("node:assert/strict");
const {spawn} = require("node:child_process");
const {mkdirSync} = require("node:fs");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");
let server, browser;

async function main() {
  mkdirSync("test-results", {recursive: true});
  let url = process.env.PLAYGROUND_URL;
  if (!url) {
    server = spawn(process.env.PYTHON || ".venv/bin/python", ["-u", "-c", "from demo.server import DemoServer; s = DemoServer(0); print(f'http://127.0.0.1:{s.server_port}', flush=True); s.serve_forever()"], {stdio: ["ignore", "pipe", "pipe"]});
    url = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("サーバーの起動期限を超えました。")), 10000);
      server.once("error", error => { clearTimeout(timer); reject(error); });
      server.once("exit", code => { clearTimeout(timer); reject(new Error(`起動失敗：${code}`)); });
      server.stderr.on("data", data => process.stderr.write(data));
      server.stdout.on("data", data => {
        const match = data.toString().match(/http:\/\/127\.0\.0\.1:\d+/);
        if (match) { clearTimeout(timer); resolve(match[0]); }
      });
    });
  }
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, reducedMotion: "reduce"});
  const failures = [];
  page.on("pageerror", error => failures.push(error.message));
  page.on("response", response => { if (response.status() >= 400) failures.push(`${response.status()} ${response.url()}`); });
  await page.goto(`${url}/landing/`);
  await page.keyboard.press("Tab");
  assert.equal(await page.locator(".skip-link").evaluate(element => element === document.activeElement), true);
  await page.keyboard.press("Enter");
  assert.equal(new URL(page.url()).hash, "#main");
  await page.getByRole("link", {name: "自社への導入を相談する"}).click();
  await page.locator("#contact").waitFor({state: "visible"});
  const contact = new URL(await page.getByRole("link", {name: "メールで相談する"}).getAttribute("href"));
  assert.equal(contact.protocol, "mailto:");
  assert.equal(contact.pathname, "omitsuhashi@the3-o.com");
  assert.ok(contact.searchParams.get("body").includes("ご相談内容"));
  assert.equal(await page.locator("form").count(), 0);

  await page.getByRole("navigation", {name: "メインナビゲーション"}).getByRole("link", {name: "ドキュメント"}).click();
  await page.getByRole("heading", {name: "自社の仕組みに、組み込む。"}).waitFor();
  await page.getByRole("link", {name: "公開APIとエラー処理（Markdown）"}).click();
  assert.ok((await page.locator("body").innerText()).includes("Python公開API"));

  for (const [label, id] of [["必要人数を変えてみる", "demand"], ["勤務ルールを試す", "consecutive_days"], ["手修正の検証を試す", "verify"]]) {
    await page.goto(`${url}/landing/`);
    await page.locator(".demo-card").filter({hasText: label}).click();
    assert.equal(new URL(page.url()).hash, `#${id}`);
    await page.locator("#feature-title").waitFor({state: "visible"});
    await page.waitForFunction(() => feature?.current && !featureController);
    assert.equal(await page.evaluate(() => feature.current.response.verification.valid), true);
    await page.getByRole("link", {name: "導入・個別開発の相談", exact: true}).click();
    assert.equal(new URL(page.url()).hash, "#contact");
  }

  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({width, height: 900});
    for (const path of ["/landing/", "/landing/docs.html"]) {
      await page.goto(url + path);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${path} / ${width}px`);
      if (path === "/landing/") await page.screenshot({path: `test-results/landing-${width}.png`, fullPage: true});
    }
  }
  const noScript = await browser.newContext({javaScriptEnabled: false, viewport: {width: 390, height: 844}});
  const staticPage = await noScript.newPage();
  await staticPage.goto(`${url}/landing/`);
  await staticPage.getByRole("link", {name: "自社への導入を相談する"}).click();
  assert.equal(new URL(staticPage.url()).hash, "#contact");
  assert.equal(await staticPage.getByRole("link", {name: "メールで相談する"}).isVisible(), true);
  await noScript.close();
  assert.deepEqual(failures, []);
  console.log("LP：問い合わせ・文書・3つの実デモ・キーボード・4画面幅・JavaScriptなしの導線確認に成功");
}

main().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server) server.kill("SIGINT");
});
