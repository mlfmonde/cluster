#
# node host/url
#
host = 'service.cluster.lab'  # dind/docker-compose.yml extra_hosts
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
    container='cluster_consul_1',
)

#
# git
#
git = dict(
    force_https=True,  # use case of no ssh credentials
)

#
# misc
#
# default timeout
timeout = 600
