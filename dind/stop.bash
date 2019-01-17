#!/usr/bin/env bash
thisDir=$(dirname "$0")
. "${thisDir}/config"
. "${thisDir}/lib.bash"

for index in ${nodes[*]}
do
    echo "stopping node ${index}..."

    # we use specific compose override file for consul config
    docker-compose exec "${nodeServicePrefix}${index}" docker-compose -f docker-compose.yml -f dind/docker-compose.dind.yml stop
done

docker-compose stop

for index in ${nodes[*]}
do
    mountDown "${index}"
done
