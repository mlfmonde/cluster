#
# node host/url
#

# use directly node 4 static ip to skip cluster_lab 'service.cluster.lab' entry /etc/hosts process
host = '10.10.77.64'  # 4th node, static IP from dind/docker-compose.yml
#host = 'service.cluster.lab'

url = 'http://' + host

#
# docker
#
docker = dict(
    # version: str, False default, 'auto': auto, 'docker version' to identify matching
    version='1.38',  # server version of consul node, dind node, ...
)

#
# consul
#
consul = dict(
    port=8500,
    container='node_consul_1',
)

#
# misc
#
# default timeout
timeout=600
