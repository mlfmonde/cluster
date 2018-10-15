#!/usr/bin/env bash
thisDir=$(dirname "$0")
. "${thisDir}/config"
. "${thisDir}/lib.bash"

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

sudo apt-get install -y qemu-utils btrfs-tools

# prepare btrfs images for each node: create image if required + mount
for index in ${nodes[*]}
do
    prepareBtrfs "${index}"
    mountUp "${index}"
    sudo mkdir "${mountPointPrefix}${index}/config"
    sudo mkdir "${mountPointPrefix}${index}/ssh"
done

# set network overlay: will force each dind node ip for convenient consul config
#docker network create -d overlay clusterlab

docker build -t anybox/cluster_node_dind .
docker-compose up -d

for index in ${nodes[*]}
do
    docker-compose exec "${nodeServicePrefix}${index}" docker plugin install --grant-all-permissions anybox/buttervolume
done
