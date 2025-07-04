const puppeteer = require('puppeteer-core');
const { Client } = require('pg');
const { MongoClient } = require('mongodb');
const fs = require('fs/promises');
const path = require('path');
const dns = require('dns').promises;
require('dotenv').config();

// MongoDB URI from environment
const MONGO_URI = process.env.MONGODB_URI || 'mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin';

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

// Enhanced workflow import and execution function - now fetches from MongoDB
async function importAndExecuteWorkflows(browser) {
  console.log('📁 Starting workflow import and execution from MongoDB...');
  
  let page;
  const deadline = Date.now() + 60000;
  
  // First try to find existing Automa dashboard
  while (!page && Date.now() < deadline) {
    page = (await browser.pages()).find(p => p.url().includes('/newtab.html'));
    if (!page) await new Promise(r => setTimeout(r, 1000));
  }
  
  // If no Automa dashboard found, create a new page and navigate to it
  if (!page) {
    console.log('📂 No Automa dashboard found, creating new tab...');
    page = await browser.newPage();
    await page.goto('chrome-extension://infppggnoaenmfagbfknfkancpbljcca/newtab.html', {
      waitUntil: 'domcontentloaded',
      timeout: 30000
    });
  }
  
  await page.waitForSelector('#app', { timeout: 20000 });

  // Fetch workflows from MongoDB instead of local files
  console.log('🔄 Fetching workflows from MongoDB...');
  const mongoClient = new MongoClient(MONGO_URI);
  let workflows = [];
  
  try {
    await mongoClient.connect();
    console.log('✅ Connected to MongoDB for workflow fetching');
    
    const db = mongoClient.db();
    const workflowsCollection = db.collection('workflows');
    
    // Fetch workflows that have URLs (updated from previous extraction)
    const mongoWorkflows = await workflowsCollection.find({ 
      url: { $exists: true },
      // Optionally filter by recent updates
      // updated_at: { $exists: true }
    }).sort({ updated_at: -1 }).toArray();
    
    console.log(`📊 Found ${mongoWorkflows.length} workflows with URLs in MongoDB`);
    
    // Convert MongoDB documents to Automa workflow format
    for (const mongoWf of mongoWorkflows) {
      // If the workflow document contains the actual workflow data
      if (mongoWf.workflow_data) {
        workflows.push(mongoWf.workflow_data);
        console.log(`✅ Loaded workflow from MongoDB: ${mongoWf.workflow_data.name || mongoWf._id}`);
      } 
      // If we need to construct a basic workflow structure
      else {
        const basicWorkflow = {
          id: mongoWf._id.toString(),
          name: mongoWf.name || `Workflow-${mongoWf._id}`,
          url: mongoWf.url,
          // Add other necessary workflow properties
          nodes: mongoWf.nodes || [],
          edges: mongoWf.edges || [],
          settings: mongoWf.settings || {},
          createdAt: mongoWf.created_at || new Date().toISOString(),
          updatedAt: mongoWf.updated_at || new Date().toISOString()
        };
        workflows.push(basicWorkflow);
        console.log(`✅ Constructed workflow from MongoDB: ${basicWorkflow.name}`);
      }
    }
    
  } catch (mongoError) {
    console.error('❌ Failed to fetch workflows from MongoDB:', mongoError.message);
    console.log('⚠️ Falling back to empty workflow list');
    workflows = [];
  } finally {
    await mongoClient.close();
  }

  if (workflows.length === 0) {
    console.log('⚠️ No workflows found to execute');
    return 0;
  }

  // Import workflows into Automa
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
      console.log(`✅ Workflow imported to Automa: ${wf.name}`);
    } catch (importError) {
      console.warn(`⚠️ Failed to import workflow ${wf.name}:`, importError.message);
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
    console.log(`▶️ Executing workflow: ${wf.name} (URL: ${wf.url || 'N/A'})`);
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

// Enhanced link extraction function with automatic navigation and MongoDB integration
async function extractLinksFromPage(browser, testMode = false, targetUrl = null) {
  console.log('🔗 Starting link extraction...');
  
  const pages = await browser.pages();
  
  // First, try to find Twitter/X pages specifically
  let page = pages.find(p => {
    const u = p.url();
    return u && (u.includes('twitter.com') || u.includes('x.com'));
  });
  
  // If no Twitter/X page found, look for any content page
  if (!page) {
    page = pages.find(p => {
      const u = p.url();
      return u &&
        !u.includes('chrome://') &&
        !u.includes('chrome-extension://') &&
        !u.includes('newtab.html') &&
        !u.includes('localhost:9222') &&
        u !== 'about:blank' &&
        u.startsWith('http');
    });
  }

  // If still no suitable page found, create one and navigate to a default URL
  if (!page) {
    console.log('📄 No suitable page found, creating new page...');
    page = await browser.newPage();
    
    // Use provided target URL or default to a sample website
    const urlToVisit = targetUrl || process.env.DEFAULT_EXTRACTION_URL || 'https://example.com';
    
    console.log(`🌐 Navigating to: ${urlToVisit}`);
    try {
      await page.goto(urlToVisit, { 
        waitUntil: 'networkidle2', 
        timeout: 30000 
      });
      
      // Wait a bit more for dynamic content
      await new Promise(r => setTimeout(r, 3000));
      
    } catch (error) {
      console.error(`❌ Failed to navigate to ${urlToVisit}:`, error.message);
      
      // Fallback to a more reliable site
      const fallbackUrl = 'https://httpbin.org/html';
      console.log(`🔄 Trying fallback URL: ${fallbackUrl}`);
      
      try {
        await page.goto(fallbackUrl, { 
          waitUntil: 'networkidle2', 
          timeout: 30000 
        });
      } catch (fallbackError) {
        console.error('❌ Fallback navigation also failed:', fallbackError.message);
        return null;
      }
    }
  }

  console.log(`🔍 Extracting from: ${page.url()}`);

  const extracted = await page.evaluate(() => {
    const links = [];
    const anchors = document.querySelectorAll('a[href]');
    
    console.log(`Found ${anchors.length} anchor elements`);
    
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
            type: 'link',
            isTwitterLink: url.hostname.includes('twitter.com') || url.hostname.includes('x.com')
          });
        } catch (e) {
          console.warn('Invalid URL:', href);
        }
      }
    });
    
    // Also get images
    const images = document.querySelectorAll('img[src]');
    console.log(`Found ${images.length} image elements`);
    
    images.forEach((img, i) => {
      const src = img.src;
      const text = ((img.alt || img.title) || '').substring(0, 200);
      if (src && !src.startsWith('data:')) {
        try {
          const url = new URL(src);
          links.push({
            index: anchors.length + i + 1,
            url: src,
            text,
            isExternal: !src.startsWith(window.location.origin),
            domain: url.hostname,
            type: 'image'
          });
        } catch (e) {
          console.warn('Invalid image URL:', src);
        }
      }
    });
    
    return {
      pageUrl: window.location.href,
      pageTitle: document.title,
      domain: window.location.hostname,
      timestamp: new Date().toISOString(),
      totalAnchors: anchors.length,
      totalImages: images.length,
      links
    };
  });

  console.log(`✅ Extracted from: ${extracted.pageUrl}`);
  console.log(`📊 Page stats: ${extracted.totalAnchors} anchors, ${extracted.totalImages} images`);
  console.log(`🔗 Found ${extracted.links.length} valid links`);
  
  // Show breakdown by type
  const linkTypes = extracted.links.reduce((acc, link) => {
    acc[link.type] = (acc[link.type] || 0) + 1;
    return acc;
  }, {});
  console.log(`📈 Link breakdown:`, linkTypes);
  
  // Show Twitter-specific links if any
  const twitterLinks = extracted.links.filter(l => l.isTwitterLink);
  if (twitterLinks.length > 0) {
    console.log(`🐦 Found ${twitterLinks.length} Twitter/X links`);
  }

  // Always save JSON for debugging
  await fs.writeFile(path.join(__dirname, 'extract_test.json'), JSON.stringify(extracted, null, 2));
  console.log(`💾 JSON exported to ${path.join(__dirname, 'extract_test.json')}`);

  if (testMode) {
    console.log('🧪 Test mode: skipping DB insert, CSV export, and MongoDB update');
    return extracted;
  }

  // Database operations (only if links were found)
  if (extracted.links.length > 0) {
    // PostgreSQL operations
    const envUrl = process.env.DATABASE_URL;
    if (!envUrl) throw new Error('DATABASE_URL not set in .env');
    const dbUrl = new URL(envUrl);
    const preferredHost = process.env.DB_HOST || dbUrl.hostname;
    const can = await canResolve(preferredHost);
    if (!can) {
      console.warn(`⚠️ Cannot resolve "${preferredHost}", switching to "localhost"`);
      dbUrl.hostname = 'localhost';
    } else {
      dbUrl.hostname = preferredHost;
    }

    const client = await connectWithRetry({ connectionString: dbUrl.toString() });

    for (const l of extracted.links) {
      await client.query(
        `INSERT INTO tweets_scraped (link) VALUES ($1) ON CONFLICT DO NOTHING`,
        [l.url]
      );
    }
    await client.end();
    console.log(`✅ URLs inserted into tweets_scraped (${extracted.links.length})`);

    // File exports
    const outDir = path.resolve(__dirname, 'extracted-links');
    await fs.mkdir(outDir, { recursive: true });
    const ts = extracted.timestamp.replace(/[:.]/g, '-');
    const base = `${extracted.domain}_${ts}`;
    await fs.writeFile(path.join(outDir, `${base}.json`), JSON.stringify(extracted, null, 2));

    const escapeCsv = s => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
    const rows = [['Index','URL','Text','Type','Domain','IsExternal']];
    extracted.links.forEach(l => rows.push([l.index, escapeCsv(l.url), escapeCsv(l.text), l.type, escapeCsv(l.domain), l.isExternal]));
    await fs.writeFile(path.join(outDir, `${base}.csv`), rows.map(r => r.join(',')).join('\n'));
    console.log(`📊 CSV saved: ${path.join(outDir, `${base}.csv`)}`);

    // MongoDB workflow update operations
    console.log('🔄 Starting MongoDB workflow updates...');
    const mongoClient = new MongoClient(MONGO_URI);
    
    try {
      await mongoClient.connect();
      console.log('✅ Connected to MongoDB');
      
      const db = mongoClient.db(); // defaults to messages_db from URI
      const workflowsCollection = db.collection('workflows');
      const timestamp = new Date().toISOString();
      
      let updatedCount = 0;
      
      for (const l of extracted.links) {
        const result = await workflowsCollection.updateOne(
          { url: { $exists: false } }, // update only if url is missing
          { 
            $set: { 
              url: l.url, 
              updated_at: timestamp,
              link_text: l.text,
              link_domain: l.domain,
              link_type: l.type,
              is_external: l.isExternal
            } 
          },
          { sort: { created_at: -1 } } // update newest first
        );
        
        if (result.modifiedCount > 0) {
          updatedCount++;
          console.log(`📝 Updated workflow with URL: ${l.url.substring(0, 60)}...`);
        }
      }
      
      console.log(`✅ Updated ${updatedCount} MongoDB workflows with URLs`);
      
      // Optional: Log total workflows without URLs remaining
      const remainingCount = await workflowsCollection.countDocuments({ url: { $exists: false } });
      console.log(`📊 Workflows still without URLs: ${remainingCount}`);
      
    } catch (mongoError) {
      console.error('❌ Failed to update MongoDB workflows:', mongoError.message);
    } finally {
      await mongoClient.close();
      console.log('🔌 MongoDB connection closed');
    }

  } else {
    console.log('⚠️ No links found, skipping database, file, and MongoDB operations');
  }

  return extracted;
}

// Main execution function
async function run() {
  const args = process.argv.slice(2);
  const testMode = args.includes('--test');
  const workflowOnly = args.includes('--workflow-only');
  const extractOnly = args.includes('--extract-only');
  
  // Get target URL from command line arguments
  const urlArgIndex = args.findIndex(arg => arg === '--url');
  const targetUrl = urlArgIndex !== -1 && args[urlArgIndex + 1] ? args[urlArgIndex + 1] : null;
  
  console.log('🚀 Starting integrated script...');
  console.log(`Mode: ${testMode ? 'TEST' : 'PRODUCTION'}`);
  if (targetUrl) {
    console.log(`Target URL: ${targetUrl}`);
  }
  
  const browser = await puppeteer.connect({
    browserURL: 'http://localhost:9222',
    defaultViewport: null,
  });

  try {
    let workflowCount = 0;
    let extractedData = null;

    // Execute workflows (unless extract-only mode)
    if (!extractOnly) {
      try {
        workflowCount = await importAndExecuteWorkflows(browser);
        console.log(`✅ Workflow phase completed: ${workflowCount} workflows processed`);
        
        // Wait a bit for workflows to potentially load new pages
        if (workflowCount > 0) {
          console.log('⏳ Waiting for workflows to complete before extraction...');
          await new Promise(r => setTimeout(r, 8000));
        }
      } catch (error) {
        console.error('❌ Workflow phase failed:', error.message);
        if (workflowOnly) {
          throw error;
        }
        console.log('⚠️ Continuing with extraction phase...');
      }
    }

    // Extract links (unless workflow-only mode)
    if (!workflowOnly) {
      try {
        extractedData = await extractLinksFromPage(browser, testMode, targetUrl);
        if (extractedData) {
          console.log(`✅ Extraction phase completed: ${extractedData.links.length} links found`);
        } else {
          console.log('⚠️ Extraction phase completed but no data extracted');
        }
      } catch (error) {
        console.error('❌ Extraction phase failed:', error.message);
        if (extractOnly) {
          throw error;
        }
      }
    }

    // Summary
    console.log('\n📋 EXECUTION SUMMARY:');
    console.log(`   Workflows processed: ${workflowCount}`);
    console.log(`   Links extracted: ${extractedData ? extractedData.links.length : 'N/A'}`);
    console.log(`   Test mode: ${testMode ? 'YES' : 'NO'}`);
    
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
Usage: node integrated-script.js [options]

Options:
  --test                Run in test mode (skip database operations)
  --workflow-only       Only execute workflows, skip link extraction
  --extract-only        Only extract links, skip workflow execution
  --url <URL>          Navigate to specific URL for extraction
  --help               Show this help message

Environment Variables:
  DEFAULT_EXTRACTION_URL   Default URL to visit if no pages are found
  DATABASE_URL            PostgreSQL connection string
  MONGODB_URI             MongoDB connection string (default: mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin)

Examples:
  node integrated-script.js                           # Run both phases in production mode
  node integrated-script.js --test                    # Run both phases in test mode
  node integrated-script.js --workflow-only           # Only import and execute workflows
  node integrated-script.js --extract-only            # Only extract links from current page
  node integrated-script.js --extract-only --url https://twitter.com  # Extract from specific URL
  `);
  process.exit(0);
}