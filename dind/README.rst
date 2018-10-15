Small private cluster
=====================

Docker in Docker
****************

For devs and CI, this Docker in docker (dind) setup is targetted for sandboxes and CI.
It aims to replace cluster_lab with Salt environnements

* one dind instance holds one cluster
* total of 4 dind instances: 4 clusters

Bootstrap
---------

    $ cd dind
    $ bash bootstrap.bash

* prepare btrfs images (4 images for 4 clusters)
* build dind docker image (dind env holds 1 cluster)
* up compose services (4 dind services for 4 clusters)

Run
---

    $ (cd dind)
    $ bash run.bash

* start dind services
* start cluster services in each dind service

Build dind image
----------------

    $ cd dind
    $ docker build -t anybox/clusterdind .
