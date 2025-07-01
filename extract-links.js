// test-updated.js
const puppeteer = require('puppeteer-core');
const { Client } = require('pg');
const fs = require('fs/promises');
const path = require('path');
require('dotenv').config();

const dns = require('dns').promises;
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

async function run(testMode = false) {
  const browser = await puppeteer.connect({
    browserURL: 'http://localhost:9222',
    defaultViewport: null,
  });

  const pages = await browser.pages();
  const page = pages.find(p => {
    const u = p.url();
    return u &&
      !u.includes('chrome://') &&
      !u.includes('chrome-extension://') &&
      !u.includes('newtab.html') &&
      u !== 'about:blank';
  });

  if (!page) {
    console.error('❌ No active webpage found.');
    return browser.disconnect();
  }

  console.log(`🔍 Extracting from: ${page.url()}`);

  const extracted = await page.evaluate(() => {
    const links = [];
    const anchors = document.querySelectorAll('a[href]');
    anchors.forEach((anchor, i) => {
      const href = anchor.href;
      const text = (anchor.textContent.trim() || anchor.title || '').substring(0, 200);
      if (href && href !== '#' && !href.startsWith('javascript:')) {
        links.push({
          index: i + 1,
          url: href,
          text,
          isExternal: !href.startsWith(window.location.origin),
          domain: new URL(href).hostname,
          type: 'link'
        });
      }
    });
    document.querySelectorAll('img[src]').forEach((img, i) => {
      const src = img.src;
      const text = ((img.alt || img.title) || '').substring(0, 200);
      if (src && !src.startsWith('data:')) {
        links.push({
          index: anchors.length + i + 1,
          url: src,
          text,
          isExternal: !src.startsWith(window.location.origin),
          domain: new URL(src).hostname,
          type: 'image'
        });
      }
    });
    return {
      pageUrl: window.location.href,
      pageTitle: document.title,
      domain: window.location.hostname,
      timestamp: new Date().toISOString(),
      links
    };
  });

  console.log(`✅ Found ${extracted.links.length} links`);
  await fs.writeFile(path.join(__dirname, 'extract_test.json'), JSON.stringify(extracted, null, 2));
  console.log(`💾 JSON exported to ${path.join(__dirname, 'extract_test.json')}`);

  if (testMode) {
    console.log('🧪 Test mode: skipping DB insert and CSV export');
    return browser.disconnect();
  }

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

  await browser.disconnect();
}

const test = process.argv.includes('--test');
run(test).catch(err => {
  console.error('❌ Fatal error:', err);
  process.exit(1);
});