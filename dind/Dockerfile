# cluster node docker in docker (dind)
FROM docker:18.06.3-dind
LABEL maintainer "Vincent GREINER <vgreiner@anybox.fr>"

ARG DOCKER_GROUP_ID

USER root

# - move ping 999 to 900 (free it for docker potentially 998/999)
# - same docker group id as host one
RUN apk update && apk --no-cache add shadow \
    && groupmod -g 900 ping \
    && echo "docker group id is: $DOCKER_GROUP_ID" \
    && addgroup -g $DOCKER_GROUP_ID docker

# - btrfs
# - docker-compose
RUN apk update && apk --no-cache add btrfs-progs py-pip \
    && pip install --upgrade pip && pip install docker-compose

# docker tcp
EXPOSE 2375
# consul
EXPOSE 8500
# others
EXPOSE 80
