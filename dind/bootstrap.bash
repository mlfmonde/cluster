#!/usr/bin/env bash
thisDir=$(dirname "$0")
. "${thisDir}/config"
. "${thisDir}/lib.bash"

echo 'hit key to continue'
read a

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

# prepare btrfs images for each cluster: create image if required + mount
for index in ${clusters[*]}
do
    prepareBtrfs "${index}"
    mountUp "${index}"
done

docker build -t anybox/clusterdind .
docker-compose up -d
