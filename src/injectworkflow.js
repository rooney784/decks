const puppeteer = require('puppeteer-core');
const fs = require('fs/promises');
const path = require('path');

(async () => {
  const browser = await puppeteer.connect({
    browserURL: 'http://localhost:9222',
    defaultViewport: null,
  });

  let page;
  const deadline = Date.now() + 60000;
  while (!page && Date.now() < deadline) {
    page = (await browser.pages()).find(p => p.url().includes('/newtab.html'));
    if (!page) await new Promise(r => setTimeout(r, 1000));
  }
  if (!page) throw new Error('Automa dashboard not found');
  await page.waitForSelector('#app', { timeout: 20000 });

  const workflowDir = path.resolve(__dirname, 'workflows');
  const files = await fs.readdir(workflowDir);
  const workflows = [];

  for (const file of files.filter(f => f.endsWith('.json'))) {
    const content = await fs.readFile(path.join(workflowDir, file), 'utf8');
    try {
      const wf = JSON.parse(content);
      workflows.push(wf);
      await page.evaluate(wf => {
        chrome.storage.local.get('workflows', res => {
          const arr = Array.isArray(res.workflows) ? res.workflows : [];
          if (!arr.find(w => w.id === wf.id)) {
            arr.unshift(wf);
            chrome.storage.local.set({ workflows: arr });
          }
        });
      }, wf);
      console.log(`✅ Workflow imported: ${wf.name}`);
    } catch {
      console.warn(`⚠️ Invalid JSON skipped: ${file}`);
    }
  }

  await Promise.all([
    page.reload({ waitUntil: ['domcontentloaded', 'networkidle0'] }),
    page.waitForNavigation({ waitUntil: ['domcontentloaded', 'networkidle0'] }),
  ]);

  console.log('🔄 Dashboard reloaded');

  // Step: Execute via background messaging
  for (const wf of workflows) {
    console.log(`▶️ Executing workflow: ${wf.name}`);
    await page.evaluate(async (workflowId) => {
      // Load the actual workflow object from storage
      const all = await chrome.storage.local.get('workflows');
      const wfObj = (all.workflows || []).find(w => w.id === workflowId);
      if (!wfObj) {
        console.error('Workflow not found:', workflowId);
        return;
      }
      // send the execution message to background script
      chrome.runtime.sendMessage({
        name: 'background--workflow:execute',
        data: { ...wfObj, options: { data: { variables: {} } } },
      });
    }, wf.id);

    // Optional: give it a moment to start
    await new Promise(r => setTimeout(r, 2000));
  }

  console.log('✅ All workflows dispatched – check Automa logs.');

  await browser.disconnect();
})();