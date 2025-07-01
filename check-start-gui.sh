# Start the container with a shell instead of GUI
docker run -it --entrypoint /bin/bash automa-chrome:latest

# Inside the container, open the script
cat /usr/local/bin/start-gui.sh
