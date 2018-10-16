#!/usr/bin/env bash
thisDir=$(dirname "$0")
. "${thisDir}/config"
. "${thisDir}/lib.bash"

#
# FUNCTIONS
#

# arg1: image index 1..N
function prepareBtrfs() {
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

# up a node
# arg1: image index 1..N
function upNode() {
    # install buttervolume docker plugin
    docker-compose exec "${nodeServicePrefix}${index}" docker plugin install --grant-all-permissions anybox/buttervolume

    # we use specific compose override file for consul config
    docker-compose exec "${nodeServicePrefix}${index}" docker-compose -f docker-compose.yml -f docker-compose.dind.yml up --force-recreate --build -d
}


#
# BODY
#
sudo apt-get install -y qemu-utils btrfs-tools

# prepare btrfs images for each node: create image if required + mount
for index in ${nodes[*]}
do
    prepareBtrfs "${index}"

    mountUp "${index}"
    createDirSudo "${mountPointPrefix}${index}/config"
    createDirSudo "${mountPointPrefix}${index}/ssh"
done

docker build -t anybox/cluster_node_dind .
docker-compose up --force-recreate -d

for index in ${nodes[*]}
do
    upNode "${index}"
done
