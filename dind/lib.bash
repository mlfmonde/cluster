# arg1: image index 1..N
function mountUp() {
    img="${btrfsImgPrefix}$1.img"
    mountDir="${mountPointPrefix}$1"
    echo "mount ${img} to ${mountDir}"

    sudo mkdir -p "${mountDir}"
    sudo mount -o loop "${img}" "${mountDir}"
}
export -f mountUp

# arg1: image index 1..N
function mountDown() {
    mountDir="${mountPointPrefix}$1"
    sudo umount "${mountDir}"
}
export -f mountDown
