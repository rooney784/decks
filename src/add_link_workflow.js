const puppeteer = require('puppeteer-core');
const { Client } = require('pg');
const { MongoClient } = require('mongodb');
const fs = require('fs/promises');
const path = require('path');
const dns = require('dns').promises;
require('dotenv').config();

// MongoDB and output settings
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin';
const OUTPUT_DIR = path.resolve(__dirname, 'workflows_updated');

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
      console.log(`🔁 PostgreSQL connect attempt ${i}/${retries}…`);
      await client.connect();
      console.log('✅ Connected to PostgreSQL');
      return client;
    } catch (err) {
      console.error(`❌ Connection attempt ${i} failed: ${err.code || err.message}`);
      if (i === retries) throw err;
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
}

async function connectToMongo() {
  const client = new MongoClient(MONGODB_URI, { serverSelectionTimeoutMS: 5000 });
  try {
    await client.connect();
    console.log('✅ Connected to MongoDB');
    return client;
  } catch (err) {
    console.error(`❌ MongoDB connection failed: ${err.message}`);
    throw err;
  }
}

// Fetch unused links from PostgreSQL
async function fetchUnusedLinks(client, limit = 10) {
  try {
    const query = `
      SELECT tweet_id, link 
      FROM tweets_scraped 
      WHERE used = FALSE 
      ORDER BY scraped_time DESC 
      LIMIT $1
    `;
    const res = await client.query(query, [limit]);
    console.log(`🔗 Fetched ${res.rows.length} unused links from PostgreSQL`);
    return res.rows.map(row => ({ tweet_id: row.tweet_id, link: row.link }));
  } catch (err) {
    console.error(`❌ Error fetching links: ${err.message}`);
    return [];
  }
}

// Mark a link as used in PostgreSQL
async function markLinkAsUsed(client, tweetId) {
  try {
    const query = `
      UPDATE tweets_scraped 
      SET used = TRUE, used_time = CURRENT_TIMESTAMP 
      WHERE tweet_id = $1
    `;
    await client.query(query, [tweetId]);
    console.log(`✅ Marked tweet_id ${tweetId} as used in PostgreSQL`);
  } catch (err) {
    console.error(`❌ Error marking tweet_id ${tweetId} as used: ${err.message}`);
  }
}

// Update workflows in MongoDB with links
async function updateWorkflowUrls(mongoClient, links) {
  try {
    const db = mongoClient.db('messages_db');
    const workflowsCollection = db.collection('workflows');
    const workflows = await workflowsCollection.find({}).toArray();
    if (!workflows.length) {
      console.log('⚠️ No workflows found in MongoDB');
      return 0;
    }

    // Ensure output directory exists
    await fs.mkdir(OUTPUT_DIR, { recursive: true });

    let updatedCount = 0;
    let linkIndex = 0;

    for (const workflow of workflows) {
      if (linkIndex >= links.length) {
        console.log('⚠️ Ran out of links to assign');
        break;
      }

      const workflowId = workflow.workflow_id;
      const workflowName = workflow.name || workflowId;
      const content = workflow.content || {};

      // Update the URL in the new-tab block
      let updated = false;
      for (const node of (content.drawflow?.nodes || [])) {
        if (node.type === 'BlockGroup') {
          for (const block of (node.data?.blocks || [])) {
            if (block.id === 'new-tab') {
              block.data.url = links[linkIndex].link;
              updated = true;
              break;
            }
          }
          if (updated) break;
        }
      }

      if (updated) {
        // Update MongoDB
        await workflowsCollection.updateOne(
          { workflow_id: workflowId },
          { $set: { content, tweet_id: links[linkIndex].tweet_id } }
        );

        // Save updated workflow to file
        const safeName = workflowName.replace(/[^a-zA-Z0-9-_]/g, '_');
        const filename = path.join(OUTPUT_DIR, `${safeName}.txt`);
        await fs.writeFile(filename, JSON.stringify(content, null, 2));
        console.log(`✅ Updated and saved workflow '${workflowName}' with link ${links[linkIndex].link} to ${filename}`);
        updatedCount++;
        linkIndex++;
      }
    }

    console.log(`🎉 Updated ${updatedCount} workflows in MongoDB`);
    return updatedCount;
  } catch (err) {
    console.error(`❌ Error updating workflows: ${err.message}`);
    return 0;
  }
}

// Link extraction function
async function extractLinksFromPage(browser, testMode = false) {
  console.log('🔗 Starting link extraction...');
  
  const pages = await browser.pages();
  
  let page = pages.find(p => {
    const u = p.url();
    return u && (u.includes('twitter.com') || u.includes('x.com'));
  });
  
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

  if (!page) {
    console.error('❌ No active webpage found for extraction.');
    console.log('Available pages:');
    pages.forEach((p, i) => console.log(`  ${i + 1}. ${p.url()}`));
    return null;
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

  console.log(`✅ Extracting from: ${extracted.pageUrl}`);
  console.log(`📊 Page stats: ${extracted.totalAnchors} anchors, ${extracted.totalImages} images`);
  console.log(`🔗 Found ${extracted.links.length} valid links`);
  
  const linkTypes = extracted.links.reduce((acc, link) => {
    acc[link.type] = (acc[link.type] || 0) + 1;
    return acc;
  }, {});
  console.log(`📈 Link breakdown:`, linkTypes);
  
  const twitterLinks = extracted.links.filter(l => l.isTwitterLink);
  if (twitterLinks.length > 0) {
    console.log(`🐦 Found ${twitterLinks.length} Twitter/X links`);
  }
  await fs.writeFile(path.join(__dirname, 'extract_test.json'), JSON.stringify(extracted, null, 2));
  console.log(`💾 JSON exported to ${path.join(__dirname, 'extract_test.json')}`);

  if (testMode) {
    console.log('🧪 Test mode: skipping DB insert and workflow update');
    return extracted;
  }

  // Database operations
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
  console.log(`✅ URLs inserted into tweets_scraped (${extracted.links.length})`);

  // Fetch unused links and update workflows in MongoDB
  const mongoClient = await connectToMongo();
  try {
    const links = await fetchUnusedLinks(client, 10); // Adjust limit as needed
    if (links.length > 0) {
      const updatedCount = await updateWorkflowUrls(mongoClient, links);
      // Mark used links
      for (const link of links.slice(0, updatedCount)) {
        await markLinkAsUsed(client, link.tweet_id);
      }
    } else {
      console.log('⚠️ No unused links found, skipping workflow update');
    }
  } finally {
    await mongoClient.close();
    console.log('🔚 MongoDB connection closed');
  }

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

  await client.end();
  console.log('🔚 PostgreSQL connection closed');

  return extracted;
}

// Main execution function
async function run() {
  const args = process.argv.slice(2);
  const testMode = args.includes('--test');
  
  console.log('🚀 Starting link extraction and workflow update...');
  console.log(`Mode: ${testMode ? 'TEST' : 'PRODUCTION'}`);
  
  const browser = await puppeteer.connect({
    browserURL: 'http://localhost:9222',
    defaultViewport: null,
  });

  try {
    const extractedData = await extractLinksFromPage(browser, testMode);
    console.log('\n📋 EXECUTION SUMMARY:');
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
Usage: node extract-and-update-workflows.js [options]

Options:
  --test           Run in test mode (skip database operations)
  --help           Show this help message

Examples:
  node extract-and-update-workflows.js         # Run in production mode
  node extract-and-update-workflows.js --test  # Run in test mode
  `);
  process.exit(0);
}