const puppeteer = require('puppeteer-core');

const workflow = {
  id: `workflow-${Date.now()}`,
  name: 'Open Google',
  description: 'Simple workflow to open Google',
  version: '1.0.0',
  drawflow: { drawflow: { Home: { data: {} } } },
  trigger: { type: 'manual' },
  settings: {}
};

(async () => {
  const browser = await puppeteer.connect({
    browserURL: 'http://localhost:9222',
    defaultViewport: null,
  });

  const start = Date.now();
  const timeout = 60000;
  let page;

  // 1️⃣ Find the Automa GUI page (newtab.html)
  while (!page && Date.now() - start < timeout) {
    const pages = await browser.pages();
    page = pages.find(p => p.url().includes('/newtab.html'));
    if (!page) await new Promise(r => setTimeout(r, 2000));
  }
  if (!page) throw new Error('Automa newtab dashboard not found');

  // Wait for the UI to be ready
  await page.waitForSelector('#app', { timeout: 20000 });

  // 2️⃣ Inject the workflow into storage
  await page.evaluate(workflowData => {
    chrome.storage.local.get('workflows', res => {
      const arr = Array.isArray(res.workflows) ? res.workflows : [];
      arr.unshift(workflowData);
      chrome.storage.local.set({ workflows: arr });
    });
  }, workflow);

  // 3️⃣ Refresh the page so the UI will pick up new storage
  await Promise.all([
    page.reload({ waitUntil: ['domcontentloaded', 'networkidle0'] }),
    page.waitForNavigation({ waitUntil: ['domcontentloaded', 'networkidle0'] })
  ]);

  console.log('🔄 Page reloaded — check GUI for new workflow!');

  await browser.disconnect();
})();
