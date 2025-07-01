const puppeteer = require('puppeteer-core');
const { MongoClient } = require('mongodb');
require('dotenv').config();

// MongoDB connection URI
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin';

// Fetch workflows from MongoDB
async function fetchWorkflowsFromMongo() {
  const client = new MongoClient(MONGODB_URI, { serverSelectionTimeoutMS: 5000 });
  try {
    await client.connect();
    console.log('✅ Connected to MongoDB');
    const db = client.db('messages_db');
    const workflowsCollection = db.collection('workflows');
    const workflowDocs = await workflowsCollection.find({}).toArray();
    // Extract the content field from each document
    const workflows = workflowDocs.map(doc => doc.content);
    console.log(`🔗 Fetched ${workflows.length} workflows from MongoDB`);
    return workflows;
  } catch (err) {
    console.error(`❌ Error fetching workflows from MongoDB: ${err.message}`);
    return [];
  } finally {
    await client.close();
    console.log('🔚 MongoDB connection closed');
  }
}

// Workflow import and execution function
async function importAndExecuteWorkflows(browser, workflows) {
  console.log('📁 Starting workflow import and execution...');
  
  let page;
  const deadline = Date.now() + 60000;
  while (!page && Date.now() < deadline) {
    page = (await browser.pages()).find(p => p.url().includes('/newtab.html'));
    if (!page) await new Promise(r => setTimeout(r, 1000));
  }
  
  if (!page) throw new Error('Automa dashboard not found');
  await page.waitForSelector('#app', { timeout: 20000 });

  // Import workflows
  for (const wf of workflows) {
    try {
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
    } catch (err) {
      console.warn(`⚠️ Error importing workflow ${wf.name || wf.id}: ${err.message}`);
    }
  }

  // Reload dashboard
  await Promise.all([
    page.reload({ waitUntil: ['domcontentloaded', 'networkidle0'] }),
    page.waitForNavigation({ waitUntil: ['domcontentloaded', 'networkidle0'] }),
  ]);

  console.log('🔄 Dashboard reloaded');

  // Execute workflows
  for (const wf of workflows) {
    console.log(`▶️ Executing workflow: ${wf.name}`);
    await page.evaluate(async (workflowId) => {
      const all = await chrome.storage.local.get('workflows');
      const wfObj = (all.workflows || []).find(w => w.id === workflowId);
      if (!wfObj) {
        console.error('Workflow not found:', workflowId);
        return;
      }
      chrome.runtime.sendMessage({
        name: 'background--workflow:execute',
        data: { ...wfObj, options: { data: { variables: {} } } },
      });
    }, wf.id);
    await new Promise(r => setTimeout(r, 2000));
  }

  console.log('✅ All workflows dispatched – check Automa logs.');
  return workflows.length;
}

// Main execution function
async function run() {
  const args = process.argv.slice(2);
  
  console.log('🚀 Starting workflow execution...');
  
  const browser = await puppeteer.connect({
    browserURL: 'http://localhost:9222',
    defaultViewport: null,
  });

  try {
    const workflows = await fetchWorkflowsFromMongo();
    let workflowCount = 0;
    if (workflows.length > 0) {
      workflowCount = await importAndExecuteWorkflows(browser, workflows);
    } else {
      console.log('⚠️ No workflows to execute');
    }
    console.log('\n📋 EXECUTION SUMMARY:');
    console.log(`   Workflows processed: ${workflowCount}`);
  } finally {
    await browser.disconnect();
    console.log('🔚 Browser disconnected');
  }
}

// Execute with error handling
run().catch(err => {
  console.error('❌ Fatal error:', err);
  process.exit(1);
});

// Help text
if (process.argv.includes('--help')) {
  console.log(`
Usage: node execute-workflows.js [options]

Options:
  --help           Show this help message

Examples:
  node execute-workflows.js         # Execute workflows
  `);
  process.exit(0);
}