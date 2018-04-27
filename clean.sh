#!/bin/bash
echo remove exited containers...
docker ps --filter status=dead --filter status=exited -aq | xargs -r docker rm -v

echo remove unused images...
docker images --no-trunc | tail -n+2 | grep '<none>' | awk '{ print $3 }' | xargs -r docker rmi

#echo remove unused volumes...
#find '/var/lib/docker/volumes/' -mindepth 1 -maxdepth 1 -type d | grep -vFf <(
#  docker ps -aq | xargs docker inspect | jq -r '.[] | .Mounts | .[] | .Name | select(.)'
#) | xargs --no-run-if-empty basename -a | xargs -r docker volume rm
