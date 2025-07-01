const { Client } = require('pg'); // or sqlite3, mysql, etc.
require('dotenv').config();

async function saveTweets(tweets) {
  const client = new Client({
    connectionString: process.env.DATABASE_URL
  });
  await client.connect();

  for (const { tweetId, url } of tweets) {
    await client.query('INSERT INTO tweets_scraped (tweet_id, url) VALUES ($1, $2) ON CONFLICT DO NOTHING', [tweetId, url]);
  }

  await client.end();
}

module.exports = { saveTweets };
