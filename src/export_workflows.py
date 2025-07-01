import json
from pymongo import MongoClient
import os

# MongoDB connection settings
# Use 'mongodb' as the hostname since it matches the Docker service name
MONGODB_URI = "mongodb://admin:admin123@mongodb:27017/messages_db?authSource=admin"
OUTPUT_DIR = "./workflows_exported"

def ensure_output_directory():
    """
    Create the output directory if it doesn't exist.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def export_workflows():
    """
    Connect to MongoDB, retrieve all workflows, and save them as .txt files.
    """
    try:
        # Connect to MongoDB
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client['messages_db']
        workflows_collection = db['workflows']
        
        # Test the connection
        client.server_info()  # Raises an exception if connection fails
        
        # Create output directory
        ensure_output_directory()
        
        # Retrieve all workflows
        workflows = workflows_collection.find()
        count = 0
        
        for workflow in workflows:
            # Use workflow_name if available, else fallback to workflow_id
            workflow_name = workflow.get('name', workflow.get('workflow_id', 'unnamed_workflow'))
            # Sanitize filename to avoid invalid characters
            safe_name = "".join(c if c.isalnum() or c in ['-', '_'] else '_' for c in workflow_name)
            filename = f"{OUTPUT_DIR}/{safe_name}.txt"
            
            # Extract the workflow content
            workflow_content = workflow.get('content', {})
            
            # Save to file
            with open(filename, 'w') as f:
                json.dump(workflow_content, f, indent=2)
            
            print(f"Saved workflow '{workflow_name}' to {filename}")
            count += 1
        
        print(f"Exported {count} workflows successfully")
        
        # Close MongoDB connection
        client.close()
        
        return count
    
    except Exception as e:
        print(f"Error exporting workflows: {str(e)}")
        return 0

if __name__ == "__main__":
    export_workflows()