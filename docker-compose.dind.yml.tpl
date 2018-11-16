# static ips v4 from 'cluster' network of dind/compose-file.yml
# bootstrap-expect = N-1 nodes
version: '3'

services:
  consul:
    container_name: cluster_consul_1
    restart: ""
    command: ["agent", "-server", "-retry-join=10.10.77.61", "-retry-join=10.10.77.62", "-retry-join=10.10.77.63", "-retry-join=10.10.77.64", "-client", "0.0.0.0", "-ui", "-bootstrap-expect=3"]
    environment:
        # important: use eth0
        CONSUL_BIND_INTERFACE: eth0
        DOCKER_HOST: {NODE_DOCKER_HOST}
    volumes:
      - consul_docker_cfg:/home/consul/.docker
      - /run/docker.sock:/run/docker.sock
      - /run/docker/plugins:/run/docker/plugins
      - /deploy:/deploy
      - caddy_conf:/consul/template/caddy/:rw
      - haproxy_conf:/consul/template/haproxy/:rw

  haproxy:
    container_name: cluster_haproxy_1
    restart: ""
    ports:
      - "80:80"
      - "443:443"
      - "1443:1443"
      - "2244:2244"

  caddy:
    container_name: cluster_caddy_1
    restart: ""

  rsyslog:
    container_name: cluster_rsyslog_1
