sudo docker build -t sensor .
sudo docker rmi $(sudo docker images -f "dangling=true" -q)
sudo su -c "docker run --rm -it --env-file <(doppler secrets download --no-file --format docker) sensor:latest"
