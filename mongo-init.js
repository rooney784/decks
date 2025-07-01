// MongoDB initialization script
// This script will be executed when MongoDB container starts

// Switch to the messages_db database
db = db.getSiblingDB('messages_db');

// Create application user with read/write permissions
db.createUser({
  user: 'app_user',
  pwd: 'app_password',
  roles: [
    {
      role: 'readWrite',
      db: 'messages_db'
    }
  ]
});

// Create collections with initial indexes
db.createCollection('messages');
db.createCollection('tweets');
db.createCollection('workflows');
db.createCollection('workflow_stats');

// Create indexes for better performance
db.messages.createIndex({ "message_id": 1 }, { unique: true });
db.messages.createIndex({ "used": 1 });
db.messages.createIndex({ "created_at": 1 });

db.tweets.createIndex({ "tweet_id": 1 }, { unique: true });
db.tweets.createIndex({ "used": 1 });
db.tweets.createIndex({ "scraped_time": 1 });

db.workflows.createIndex({ "workflow_id": 1 }, { unique: true });
db.workflows.createIndex({ "created_at": 1 });
db.workflows.createIndex({ "tweet_id": 1 });
db.workflows.createIndex({ "message_id": 1 });

db.workflow_stats.createIndex({ "date": 1 });
db.workflow_stats.createIndex({ "hour": 1 });

print('MongoDB initialization completed successfully');