#!/usr/bin/env bash
thisDir=$(dirname "$0")
. "${thisDir}/config"
. "${thisDir}/lib.bash"

echo 'hit key to continue'
read a

for index in ${clusters[*]}
do
    mountUp "${index}"
done

docker-compose start

for index in ${clusters[*]}
    docker-compose exec "${clusterServicePrefix}${index}" docker-compose up -d
done
