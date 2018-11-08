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
do
    echo "running node ${index}..."

    # we use specific compose override file for consul config
    docker-compose exec "${nodeServicePrefix}${index}" docker-compose -f docker-compose.yml -f "docker-compose.dind.node${index}.generated.yml" start
    docker-compose exec "${nodeServicePrefix}${index}" docker-compose exec consul buttervolume run&
done
