Small private cluster
=====================

Docker in Docker
****************

For devs and CI, this Docker in docker (dind) setup is targetted for sandboxes and CI.
It aims to replace cluster_lab with Salt envs.

* one dind instance represents 1 node, where this repo 'cluster' is installed on each node
* 1 sandbox/CI cluster is a total of 4 nodes: 4 dind instances

Bootstrap
---------
::
    $ cd dind
    $ bash bootstrap.bash

* prepare btrfs images (4 images for 4 nodes)
* build dind docker image (dind env holds 1 node)
* up compose services (1 cluster of 4 dind nodes)

to note that bootstrap start too nodes

Start
-----
::
    $ (cd dind)
    $ bash start.bash

* start already bootstraped dind services
* start cluster services in each dind service

Build dind image
----------------
::
    $ cd dind
    $ docker build -t anybox/clusterdind .
