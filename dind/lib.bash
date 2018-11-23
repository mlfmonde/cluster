#!/usr/bin/env bash

# create dir
function createDirSudo() {
    echo "create dir $1"
    if sudo bash -c "[[ -d $1 ]]"; then
        echo "$1 already exist"
    else
        sudo mkdir -p "$1"
    fi
}
export -f createDirSudo

function createDir() {
    echo "create dir $1"
    if "[[ -d $1 ]]"; then
        echo "$1 already exist"
    else
        mkdir -p "$1"
    fi
}
export -f createDir

# mount directory
# arg1: image index 1..N
function mountUp() {
    img="${btrfsImgPrefix}$1.img"
    mountDir="${mountPointPrefix}$1"
    echo "mount ${img} to ${mountDir}"

    sudo mkdir -p "${mountDir}"
    sudo mount -o loop "${img}" "${mountDir}"
}
export -f mountUp

# unmount directory
# arg1: image index 1..N
function mountDown() {
    mountDir="${mountPointPrefix}$1"
    sudo umount "${mountDir}"
}
export -f mountDown

# remove image
# arg1: image index 1..N
function removeImg() {
    img="${btrfsImgPrefix}$1.img"
    echo "Removing btrfs ${img} image"

    if sudo true; then
        sudo rm -f ${img}
    else
        echo "ERROR: sudo required"
    fi
}