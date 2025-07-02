// MongoDB workflow update operations - UPDATED VERSION
console.log('🔄 Starting MongoDB workflow updates...');
const mongoClient = new MongoClient(MONGO_URI);

try {
  await mongoClient.connect();
  console.log('✅ Connected to MongoDB');
  
  const db = mongoClient.db(); // defaults to messages_db from URI
  const workflowsCollection = db.collection('workflows');
  const timestamp = new Date().toISOString();
  
  let updatedCount = 0;
  
  // First, check how many workflows have www.kimu.com
  const kimuWorkflowsCount = await workflowsCollection.countDocuments({ url: 'www.kimu.com' });
  console.log(`📊 Found ${kimuWorkflowsCount} workflows with www.kimu.com to update`);
  
  if (kimuWorkflowsCount === 0) {
    console.log('⚠️ No workflows with www.kimu.com found to update');
  } else {
    for (const l of extracted.links) {
      const result = await workflowsCollection.updateOne(
        { url: 'www.kimu.com' }, // specifically target workflows with www.kimu.com
        { 
          $set: { 
            url: l.url, 
            updated_at: timestamp,
            link_text: l.text,
            link_domain: l.domain,
            link_type: l.type,
            is_external: l.isExternal,
            previous_url: 'www.kimu.com' // optional: keep track of what was replaced
          } 
        },
        { sort: { created_at: -1 } } // update newest first
      );
      
      if (result.modifiedCount > 0) {
        updatedCount++;
        console.log(`📝 Replaced www.kimu.com with: ${l.url.substring(0, 60)}...`);
        
        // Optional: break if you want one-to-one replacement
        // If you have more workflows than links, some will remain as www.kimu.com
        // If you have more links than workflows, some links won't be assigned
      }
    }
  }
  
  console.log(`✅ Updated ${updatedCount} MongoDB workflows, replacing www.kimu.com with extracted URLs`);
  
  // Optional: Log remaining workflows with www.kimu.com
  const remainingKimuCount = await workflowsCollection.countDocuments({ url: 'www.kimu.com' });
  if (remainingKimuCount > 0) {
    console.log(`📊 Workflows still with www.kimu.com: ${remainingKimuCount}`);
  }
  
} catch (mongoError) {
  console.error('❌ Failed to update MongoDB workflows:', mongoError.message);
} finally {
  await mongoClient.close();
  console.log('🔌 MongoDB connection closed');
}