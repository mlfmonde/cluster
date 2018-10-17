# cluster node docker in docker (dind)
FROM docker:stable-dind
LABEL maintainer "Vincent GREINER <vgreiner@anybox.fr>"

ARG DOCKER_GROUP_ID

USER root

# same docker group id as host one
RUN echo "docker group id is: $DOCKER_GROUP_ID" && addgroup -g $DOCKER_GROUP_ID docker

RUN apk update && apk add btrfs-progs py-pip

# docker-compose: for alpine we install it via pip (KO if you follow docker-compose install documentation)
RUN pip install --upgrade pip && pip install docker-compose

# docker tcp
EXPOSE 2375
# consul
EXPOSE 8500
# others
EXPOSE 80
