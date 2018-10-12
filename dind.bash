#!/usr/bin/env bash
echo 'hit key to continue'
read a

btrfsImgPath='/var/lib/docker'

# small dind dev/testing size
btrfsImgSize='1G'
# dev host size
#btrfsImgSize='10G'

mountPointPrefix='/mnt/cluster'

clusters=("1")
#clusters=("1" "2" "3" "4")


# arg1: image index 1..N
function prepareBtrfs() {
    img="${btrfsImgPath}/btrfs$1.img"
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

# arg1: image index 1..N
function mountUp() {
    img="${btrfsImgPath}/btrfs$1.img"
    mountDir="${mountPointPrefix}$1"
    echo "mount ${img} to ${mountDir}"

    sudo mkdir -p "${mountDir}"
    sudo mount -o loop "${img}" "${mountDir}"
}

# arg1: image index 1..N
function mountDown() {
    mountDir="${mountPointPrefix}$1"
    sudo umount "${mountDir}"
}

sudo apt-get install -y qemu-utils btrfs-tools

# prepare btrfs images for each cluster: create image if required + mount
for index in ${clusters[*]}
do
    prepareBtrfs "${index}"
    mountUp "${index}"
done

#docker build -t anybox/clusterdind -f ./dind/Dockerfile ./dind
#docker run --privileged --name "${name}" -d anybox/clusterdind

echo 'finished. hit key to continue'
read a
