#!/usr/bin/env bash
thisDir=$(dirname "$0")
. "${thisDir}/config"
. "${thisDir}/lib.bash"


docker-compose down -v

for index in ${nodes[*]}
do
    mountDown "${index}"
    removeImg "${index}"
done
