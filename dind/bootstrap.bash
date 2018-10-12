#!/usr/bin/env bash
thisDir=$(dirname "$0")
. "${thisDir}/config"
. "${thisDir}/lib.bash"

#
# FUNCTIONS
#

function envSet() {
    echo 'set env'
    export DOCKER_GROUP_ID=`getent group docker | cut -d: -f3`
    echo "docker group id: ${DOCKER_GROUP_ID}"
}

# arg1: image index 1..N
function btrfsCreateImage() {
    img="${btrfsImgPrefix}$1.img"
    echo "prepare btrfs ${img} image"

    if sudo true; then
        if sudo bash -c "[[ -f ${img} ]]"; then
            echo "image already exist. skipped"
        else
            echo ""
            echo "creating ${img} ${btrfsImgSize} image..."
            sudo qemu-img create "${img}" "${btrfsImgSize}"
            echo "btrfs mkfs in progress..."
            sudo mkfs.btrfs "${img}"
        fi
    else
        echo "ERROR: sudo required"
    fi
}

function btrfsUp() {
    btrfsCreateImage "$1"

    mountUp "$1"
    createDirSudo "${mountPointPrefix}$1/config"
    createDirSudo "${mountPointPrefix}$1/ssh"

    # copy ssh keys
    userDir=`pwd`
    echo "deploying ssh keys"
    sudo cp ${userDir}/file/ssh/* "${mountPointPrefix}$1/ssh/"
    # copy ssh config
    echo "deploying ssh config"
    sudo cp ${userDir}/file/ssh/config "${mountPointPrefix}$1/ssh/"
}

# up a node
# arg1: image index 1..N
function nodeUp() {
    echo "bootstrapping node $1..."

    # install buttervolume docker plugin
    docker-compose exec "${nodeServicePrefix}$1" docker plugin install --grant-all-permissions anybox/buttervolume
    docker-compose exec "${nodeServicePrefix}$1" docker plugin ls

    # we use specific compose override file for consul config
    # based on a template generated for each node
    composeFileTemplatePath="$(pwd)/../docker-compose.dind.yml.tpl"
    composeFileGenerated="docker-compose.dind.node$1.generated.yml"
    composeFileGeneratedPath="$(pwd)/../${composeFileGenerated}"
    nodeDockerHost="10.10.77.6$1:2375"
    cp -f "${composeFileTemplatePath}" "${composeFileGeneratedPath}"
    sed -i -e "s/{NODE_DOCKER_HOST}/${nodeDockerHost}/g" "${composeFileGeneratedPath}"
    docker-compose exec "${nodeServicePrefix}$1" docker-compose -f docker-compose.yml -f "${composeFileGenerated}" up --force-recreate --build -d

    #docker-compose exec "${nodeServicePrefix}$1" docker-compose exec consul buttervolume run&

    # display env
    docker-compose exec "${nodeServicePrefix}$1" docker-compose exec consul sh -c "env"
}


#
# BODY
#
envSet
sudo apt-get install -y qemu-utils btrfs-tools

# btrfs
for index in ${nodes[*]}
do
    btrfsUp "${index}"
done

# up nodes
docker-compose up --force-recreate --build -d
for index in ${nodes[*]}
do
    nodeUp "${index}"
done
