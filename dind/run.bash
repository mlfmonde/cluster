#!/usr/bin/env bash
thisDir=$(dirname "$0")
. "${thisDir}/config"
. "${thisDir}/lib.bash"

for index in ${nodes[*]}
do
    mountUp "${index}"
done

docker-compose start

for index in ${nodes[*]}
    docker-compose exec "${nodeServicePrefix}${index}" docker-compose up -d
done
