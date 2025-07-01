# Remove existing containers and volumes
docker-compose down --volumes --remove-orphans

# Create required directories
mkdir -p airflow/logs screenshots extracted-links workflows

# Set permissions
chown -R 1000:0 airflow/logs screenshots

# Rebuild and start
docker-compose up --build