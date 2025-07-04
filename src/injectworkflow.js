const puppeteer = require('puppeteer-core');
const { MongoClient } = require('mongodb');
const { Client } = require('pg');
const fs = require('fs/promises');
const path = require('path');
const dns = require('dns').promises;
require('dotenv').config();

// Configuration
const MONGO_URI = process.env.MONGODB_URI || 'mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin';
const CHROME_DEBUG_URL = process.env.CHROME_DEBUG_URL || 'http://chrome-gui:9222';
const CHROME_VNC_URL = process.env.CHROME_VNC_URL || 'http://chrome-gui:6080';

// Helper functions
async function canResolve(hostname) {
  try {
    await dns.lookup(hostname);
    return true;
  } catch {
    return false;
  }
}

async function connectWithRetry(config, retries = 5, delayMs = 2000) {
  for (let i = 1; i <= retries; i++) {
    const client = new Client(config);
    try {
      console.log(`🔁 DB connect attempt ${i}/${retries}…`);
      await client.connect();
      console.log('✅ Connected to the database');
      return client;
    } catch (err) {
      console.error(`❌ Connection attempt ${i} failed: ${err.code || err.message}`);
      if (i === retries) throw err;
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
}

// Connect to existing Chrome instance via Chrome GUI
async function connectToChrome() {
  console.log(`🔗 Connecting to Chrome GUI at ${CHROME_DEBUG_URL}`);
  console.log(`🖥️ VNC access available at ${CHROME_VNC_URL}`);
  
  try {
    const browser = await puppeteer.connect({
      browserURL: CHROME_DEBUG_URL,
      defaultViewport: null,
    });
    
    // Verify connection
    const version = await browser.version();
    console.log(`✅ Connected to Chrome GUI: ${version}`);
    
    return browser;
  } catch (error) {
    console.error(`❌ Failed to connect to Chrome GUI at ${CHROME_DEBUG_URL}`);
    console.error(`Check if Chrome GUI container is running and accessible`);
    console.error(`VNC interface should be available at: ${CHROME_VNC_URL}`);
    throw error;
  }
}

// Find or create Automa dashboard page
async function getAutomaDashboard(browser) {
  const pages = await browser.pages();
  
  // Look for existing Automa dashboard
  let automaPage = pages.find(page => {
    const url = page.url();
    return url.includes('/newtab.html') || url.includes('automa') || url.includes('infppggnoaenmfagbfknfkancpbljcca');
  });
  
  if (automaPage) {
    console.log(`✅ Found existing Automa dashboard: ${automaPage.url()}`);
    return automaPage;
  }
  
  // Create new Automa dashboard page
  console.log('📂 Creating new Automa dashboard...');
  automaPage = await browser.newPage();
  
  // Try common Automa extension URLs
  const automaUrls = [
    'chrome-extension://infppggnoaenmfagbfknfkancpbljcca/newtab.html',
    'chrome-extension://infppggnoaenmfagbfknfkancpbljcca/dashboard.html',
    'chrome://extensions/', // Fallback to extensions page
  ];
  
  for (const url of automaUrls) {
    try {
      console.log(`🔄 Trying to navigate to: ${url}`);
      await automaPage.goto(url, { waitUntil: 'domcontentloaded', timeout: 10000 });
      
      // Check if page loaded successfully
      const title = await automaPage.title();
      console.log(`📄 Page title: ${title}`);
      
      if (title.toLowerCase().includes('automa') || url.includes('newtab.html')) {
        console.log('✅ Successfully loaded Automa dashboard');
        return automaPage;
      }
    } catch (error) {
      console.warn(`⚠️ Failed to load ${url}: ${error.message}`);
    }
  }
  
  throw new Error('Could not load Automa dashboard. Make sure Automa extension is installed and enabled.');
}

// Import and execute workflows from MongoDB
async function importAndExecuteWorkflows(browser) {
  console.log('📁 Starting workflow import and execution from MongoDB...');
  
  // Get Automa dashboard
  const page = await getAutomaDashboard(browser);
  
  // Wait for Automa to fully load
  try {
    await page.waitForSelector('#app, .dashboard, [data-testid="dashboard"]', { timeout: 20000 });
    console.log('✅ Automa dashboard loaded');
  } catch (error) {
    console.warn('⚠️ Could not detect Automa dashboard elements, proceeding anyway...');
  }
  
  // Fetch workflows from MongoDB
  console.log('🔄 Fetching workflows from MongoDB...');
  const mongoClient = new MongoClient(MONGO_URI);
  let workflows = [];
  
  try {
    await mongoClient.connect();
    console.log('✅ Connected to MongoDB for workflow fetching');
    
    const db = mongoClient.db();
    const workflowsCollection = db.collection('workflows');
    
    // Fetch workflows
    const mongoWorkflows = await workflowsCollection.find({}).sort({ updated_at: -1 }).toArray();
    console.log(`📊 Found ${mongoWorkflows.length} workflows in MongoDB`);
    
    // Convert MongoDB documents to Automa workflow format
    for (const mongoWf of mongoWorkflows) {
      if (mongoWf.workflow_data) {
        workflows.push(mongoWf.workflow_data);
        console.log(`✅ Loaded workflow: ${mongoWf.workflow_data.name || mongoWf._id}`);
      } else {
        // Create basic workflow structure
        const basicWorkflow = {
          id: mongoWf._id.toString(),
          name: mongoWf.name || `Workflow-${mongoWf._id}`,
          url: mongoWf.url || '',
          nodes: mongoWf.nodes || [],
          edges: mongoWf.edges || [],
          settings: mongoWf.settings || {},
          createdAt: mongoWf.created_at || new Date().toISOString(),
          updatedAt: mongoWf.updated_at || new Date().toISOString()
        };
        workflows.push(basicWorkflow);
        console.log(`✅ Constructed workflow: ${basicWorkflow.name}`);
      }
    }
    
  } catch (mongoError) {
    console.error('❌ Failed to fetch workflows from MongoDB:', mongoError.message);
    return 0;
  } finally {
    await mongoClient.close();
  }

  if (workflows.length === 0) {
    console.log('⚠️ No workflows found to execute');
    return 0;
  }

  // Import workflows into Automa
  console.log('📥 Importing workflows into Automa...');
  for (const wf of workflows) {
    try {
      await page.evaluate(workflow => {
        return new Promise((resolve) => {
          chrome.storage.local.get('workflows', (result) => {
            const existingWorkflows = Array.isArray(result.workflows) ? result.workflows : [];
            
            // Check if workflow already exists
            const existingIndex = existingWorkflows.findIndex(w => w.id === workflow.id);
            
            if (existingIndex >= 0) {
              // Update existing workflow
              existingWorkflows[existingIndex] = workflow;
              console.log(`Updated existing workflow: ${workflow.name}`);
            } else {
              // Add new workflow
              existingWorkflows.unshift(workflow);
              console.log(`Added new workflow: ${workflow.name}`);
            }
            
            chrome.storage.local.set({ workflows: existingWorkflows }, () => {
              resolve();
            });
          });
        });
      }, wf);
      
      console.log(`✅ Workflow imported: ${wf.name}`);
    } catch (importError) {
      console.warn(`⚠️ Failed to import workflow ${wf.name}:`, importError.message);
    }
  }

  // Reload dashboard to show new workflows
  console.log('🔄 Reloading Automa dashboard...');
  await page.reload({ waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 3000)); // Give time to reload

  // Execute workflows
  console.log('▶️ Starting workflow execution...');
  let executedCount = 0;
  
  for (const wf of workflows) {
    try {
      console.log(`🚀 Executing workflow: ${wf.name}`);
      
      const executionResult = await page.evaluate(async (workflowId) => {
        return new Promise((resolve) => {
          chrome.storage.local.get('workflows', (result) => {
            const workflows = result.workflows || [];
            const workflow = workflows.find(w => w.id === workflowId);
            
            if (!workflow) {
              resolve({ success: false, error: 'Workflow not found' });
              return;
            }
            
            // Execute workflow
            chrome.runtime.sendMessage({
              name: 'background--workflow:execute',
              data: { 
                ...workflow, 
                options: { data: { variables: {} } } 
              },
            }, (response) => {
              resolve({ success: true, response });
            });
          });
        });
      }, wf.id);
      
      if (executionResult.success) {
        console.log(`✅ Workflow executed successfully: ${wf.name}`);
        executedCount++;
      } else {
        console.warn(`⚠️ Workflow execution failed: ${wf.name} - ${executionResult.error}`);
      }
      
      // Wait between executions
      await new Promise(r => setTimeout(r, 2000));
      
    } catch (execError) {
      console.warn(`⚠️ Error executing workflow ${wf.name}:`, execError.message);
    }
  }

  console.log(`✅ Workflow execution completed: ${executedCount}/${workflows.length} workflows executed`);
  return executedCount;
}

// Enhanced link extraction from current pages
async function extractLinksFromPages(browser, testMode = false) {
  console.log('🔗 Starting link extraction from browser pages...');
  
  const pages = await browser.pages();
  const validPages = pages.filter(page => {
    const url = page.url();
    return url && 
           !url.includes('chrome://') && 
           !url.includes('chrome-extension://') && 
           !url.includes('chrome-gui:9222') && 
           !url.includes('chrome-gui:6080') &&
           url !== 'about:blank' && 
           url.startsWith('http');
  });
  
  console.log(`📄 Found ${validPages.length} valid pages for extraction`);
  
  if (validPages.length === 0) {
    console.log('⚠️ No valid pages found for link extraction');
    return null;
  }
  
  const allExtracted = [];
  
  for (const page of validPages) {
    try {
      console.log(`🔍 Extracting from: ${page.url()}`);
      
      const extracted = await page.evaluate(() => {
        const links = [];
        const anchors = document.querySelectorAll('a[href]');
        
        anchors.forEach((anchor, i) => {
          const href = anchor.href;
          const text = (anchor.textContent.trim() || anchor.title || anchor.getAttribute('aria-label') || '').substring(0, 200);
          
          if (href && href !== '#' && !href.startsWith('javascript:')) {
            try {
              const url = new URL(href);
              links.push({
                index: i + 1,
                url: href,
                text,
                isExternal: !href.startsWith(window.location.origin),
                domain: url.hostname,
                type: 'link'
              });
            } catch (e) {
              // Skip invalid URLs
            }
          }
        });
        
        return {
          pageUrl: window.location.href,
          pageTitle: document.title,
          domain: window.location.hostname,
          timestamp: new Date().toISOString(),
          totalLinks: links.length,
          links
        };
      });
      
      if (extracted.links.length > 0) {
        allExtracted.push(extracted);
        console.log(`✅ Extracted ${extracted.links.length} links from ${extracted.pageTitle}`);
      }
      
    } catch (error) {
      console.warn(`⚠️ Failed to extract from page: ${error.message}`);
    }
  }
  
  if (allExtracted.length === 0) {
    console.log('⚠️ No links extracted from any page');
    return null;
  }
  
  // Combine all extracted data
  const combinedData = {
    timestamp: new Date().toISOString(),
    totalPages: allExtracted.length,
    totalLinks: allExtracted.reduce((sum, page) => sum + page.links.length, 0),
    pages: allExtracted,
    allLinks: allExtracted.flatMap(page => page.links)
  };
  
  console.log(`📊 Total extraction: ${combinedData.totalLinks} links from ${combinedData.totalPages} pages`);
  
  if (testMode) {
    console.log('🧪 Test mode: saving results to file only');
    await fs.writeFile('extracted_links_test.json', JSON.stringify(combinedData, null, 2));
    return combinedData;
  }
  
  // Save to database if not in test mode
  if (process.env.DATABASE_URL) {
    try {
      const dbUrl = new URL(process.env.DATABASE_URL);
      const client = await connectWithRetry({ connectionString: dbUrl.toString() });
      
      for (const link of combinedData.allLinks) {
        await client.query(
          'INSERT INTO tweets_scraped (link) VALUES ($1) ON CONFLICT DO NOTHING',
          [link.url]
        );
      }
      
      await client.end();
      console.log(`✅ Saved ${combinedData.totalLinks} links to database`);
    } catch (dbError) {
      console.error('❌ Failed to save to database:', dbError.message);
    }
  }
  
  return combinedData;
}

// Main execution function
async function main() {
  const args = process.argv.slice(2);
  const testMode = args.includes('--test');
  const workflowOnly = args.includes('--workflow-only');
  const extractOnly = args.includes('--extract-only');
  const help = args.includes('--help');
  
  if (help) {
    console.log(`
Usage: node script.js [options]

Options:
  --test              Run in test mode (no database operations)
  --workflow-only     Only execute workflows
  --extract-only      Only extract links
  --help              Show this help

Environment Variables:
  MONGODB_URI         MongoDB connection string
  DATABASE_URL        PostgreSQL connection string
  CHROME_DEBUG_URL    Chrome GUI debug URL (default: http://chrome-gui:9222)
  CHROME_VNC_URL      Chrome GUI VNC URL (default: http://chrome-gui:6080)

Examples:
  node script.js                    # Run both workflows and extraction
  node script.js --test             # Test mode (no database saves)
  node script.js --workflow-only    # Only execute workflows
  node script.js --extract-only     # Only extract links
    `);
    return;
  }
  
  console.log('🚀 Starting workflow and extraction script...');
  console.log(`Mode: ${testMode ? 'TEST' : 'PRODUCTION'}`);
  console.log(`Chrome GUI Debug: ${CHROME_DEBUG_URL}`);
  console.log(`Chrome GUI VNC: ${CHROME_VNC_URL}`);
  
  let browser;
  
  try {
    browser = await connectToChrome();
    
    let workflowCount = 0;
    let extractedData = null;
    
    // Execute workflows
    if (!extractOnly) {
      try {
        workflowCount = await importAndExecuteWorkflows(browser);
        console.log(`✅ Workflow phase completed: ${workflowCount} workflows processed`);
        
        if (workflowCount > 0) {
          console.log('⏳ Waiting for workflows to load pages...');
          await new Promise(r => setTimeout(r, 10000));
        }
      } catch (error) {
        console.error('❌ Workflow phase failed:', error.message);
        if (workflowOnly) throw error;
      }
    }
    
    // Extract links
    if (!workflowOnly) {
      try {
        extractedData = await extractLinksFromPages(browser, testMode);
        console.log(`✅ Extraction phase completed`);
      } catch (error) {
        console.error('❌ Extraction phase failed:', error.message);
        if (extractOnly) throw error;
      }
    }
    
    // Summary
    console.log('\n📋 EXECUTION SUMMARY:');
    console.log(`   Chrome GUI Debug: ${CHROME_DEBUG_URL}`);
    console.log(`   Chrome GUI VNC: ${CHROME_VNC_URL}`);
    console.log(`   Workflows executed: ${workflowCount}`);
    console.log(`   Links extracted: ${extractedData ? extractedData.totalLinks : 'N/A'}`);
    console.log(`   Pages processed: ${extractedData ? extractedData.totalPages : 'N/A'}`);
    console.log(`   Test mode: ${testMode ? 'YES' : 'NO'}`);
    
  } catch (error) {
    console.error('❌ Fatal error:', error.message);
    process.exit(1);
  } finally {
    if (browser) {
      await browser.disconnect();
      console.log('🔚 Disconnected from Chrome GUI');
    }
  }
}

// Run the script
main().catch(console.error);