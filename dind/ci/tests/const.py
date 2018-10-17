# use directly node 4 static ip to skip cluster_lab 'service.cluster.lab' entry /etc/hosts process
host = '10.10.77.64'  # static IP from dind/docker-compose.yml
#host = 'service.cluster.lab'

url = 'http://' + host
