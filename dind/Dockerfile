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

# btrfs
RUN apk update && apk --no-cache add btrfs-progs

# latest docker-compose via pip
RUN apk update && apk --no-cache add build-base curl git python-dev py-pip openssl-dev libffi-dev \
    && pip install --upgrade pip && pip install docker-compose

# freezed docker-compose via release
# RUN apk update && apk --no-cache add curl py-pip python-dev libffi-dev openssl-dev gcc libc-dev make \
#     && curl -L "https://github.com/docker/compose/releases/download/1.24.1/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose \
#     && chmod +x /usr/local/bin/docker-compose

# docker tcp
EXPOSE 2375
# consul
EXPOSE 8500
# others
EXPOSE 80
