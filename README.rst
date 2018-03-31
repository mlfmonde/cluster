.. image:: https://travis-ci.org/mlfmonde/cluster.svg?branch=master
   :target: https://travis-ci.org/mlfmonde/cluster
   :alt: Travis state

Small private cluster
=====================

Original vision
***************

This repository contains a self-sufficient configuration allowing to set-up a
small private cluster to deploy, manage and host your common linux-based web applications.

The original goal was to scatter many applications across a cluster by pairs of
nodes: one active node where the application runs and one passive node where
data is replicated. Each node can then be an active node for an application and
a passive node for another one, so that applications can be quickly moved to
their passive node, to balance the load across the cluster.

It is designed with the following goals in mind:

    * **Open source** : configuration and all components provided and open-source
    * **Masterless** : every node at the same level - no single point of failure
    * **Generic** : should support any linux-based web application with any database
    * **Affordable** : should allow to build a low-cost hosting/CI infrastructure
    * **Replicated** : data should be replicated on at least two nodes
    * **Snapshotted** : applications can be instantaneously rollbacked to an earlier state (last hour, last day, last week, etc.)
    * **Good performance** : no overhead compared to a typical legacy hosting infrastructure
    * **Easily maintained** : cluster nodes can be easily maintained and replaced
    * **Flexible** : applications can be quickly moved to another host
    * **Secure** : applications should be protected by automated TLS certificates
    * **Automated** : no manual action on the nodes should be required
    * **Multitenant** : external people can also deploy applications
    * **Monitored** : light monitoring should be included 
    * **Extendable** : new nodes can be easily added (or removed)
    * **Easily configurable** : simple applications should be described by a single file
    * **User friendly** : nice user interface to manage the applications

We are not talking about a large googlesque public cloud of stateless applications,
but a small private cluster of common applications used by most companies, such as Wordpress, Drupal,
Moodle, Odoo, Nextcloud, Gitlab, etc.

Current implementation
**********************

The current implementation is based on the following components :

    * `CoreOs Container Linux <https://coreos.com/>`_
    * `Docker <https://www.docker.com/>`_
    * `Docker Compose <https://docs.docker.com/compose/>`_
    * `Buttervolume <https://pypi.python.org/pypi/buttervolume>`_
    * `HAProxy <https://www.haproxy.org/>`_
    * `Caddy <https://caddyserver.com/>`_
    * `Consul <https://www.consul.io/>`_
    * `Consul Template <https://github.com/hashicorp/consul-template>`_

How does it work?
*****************

Several nodes of the cluster should be registered as a round-robin DNS under a
common name, such as cluster.yourdomain.tld. Applications should then be
registered as a CNAME of cluster.yourdomain.tld. A requests can hit any of the
nodes, it will be TCP-redirected by HAProxy to the node where the application
lives. Another HAProxy then forwards the requests to a local Caddy reverse
proxy which automatically manages the TLS certificates. The Caddy finally
forwards the request to the expected Docker container inside the node.  To
deploy an application, you just send a JSON message to Consul, which transmits
the message to all nodes of the cluster. Each node separately handles the
message with a custom Python handler and take the appropriate decision, such as
stopping an application, pulling the new version, moving the volumes to the
right node, starting the application on the correct node, registering
application metadata in the key-value store of Consul, or setting up the
monitoring for the application.  Cooperation between nodes is achieved through
reads and writes of expirable locking informations in the key-value store. Each
application is started on an active node and its volumes are asynchronously
replicated on a passive node with Buttervolume, which also periodically
snapshot the volumes, allowing to rollback to a previous state. This allows to
quicly move any application to its passive node with a few seconds downtime at
most. Applications thus live on a single node as they would run on a standalone
machine, but are scatered through the cluster and replicated on at least two
nodes.

Future improvements
*******************

- Allow to load-balance eligible applications on several nodes
- Allow to setup a synchronous database replication on several nodes
- Design a nice user interface to manage deployments, snaphots, volume, and so on
- Include a gitlab (or other forge) configuration with a docker registry
- ...

Cluster management
==================

Basic actions
*************

Start
-----

* First start the btrfs volume plugin for docker separately::

    $ pushd buttervolume
    $ docker-compose up -d

* overwrite ``command`` and environment variables in ``docker-compose.yml``
  with a ``docker-compose.override.yml`` that may looks like::

   version: '3'
   services:
     consul:
       command: ["agent", "-server", "-retry-join=10.10.20.1", "-retry-join=10.10.20.2", "-retry-join=10.10.20.3", "-ui"]
       environment:
           CONSUL_BIND_INTERFACE: eth1

* Then start caddy, haproxy and consul::

    $ popd
    $ docker-compose up -d


* buttervolume ssh configuration

* caddy /srv maintenance page volume configuration

* consul ssh configuration


Rebuild and restart
-------------------
::
    $ docker-compose up -d --build


Stop
----

Same in reverse order::

    $ docker-compose down
    $ cd buttervolume
    $ docker-compose down


Consul web UI
-------------

The consul web UI runs on http://127.0.0.1:8500 on the host, through the consul docker running in host network_driver mode.
To access it from outside, create a ssh tunnel::

    $ ssh -L 8500:localhost:8500 user@node1.example.com
    $ firefox localhost:8500


Deploy or move an app
---------------------

connect on any node, then run this from the cluster/ directory::

    docker-compose exec consul consul event -name=deploy '{"master": "<master_node>", "slave": "<slave_node>", "branch": "<branch_name>", "repo": "<repository_url>"}'

Example: deploy foobar on node1 and replicate on node2::

    docker-compose exec consul consul event -name=deploy '{"master": "node1", "slave": "node2", "branch": "master", "repo": "ssh://git@gitlab.example.com/hosting/foobar"}

During deployment, volumes are automatically moved to the new master node.

Local development environment
-----------------------------

All docker containers can be used partially (not with ssl website) on the
developer host.

.. note::

    You can use a self signed certificate by adding ``tls self_signed`` in the
    CADDYFILE environment variable in the docker-compose service.

You need to edit ``docker-compose.dev.yml`` and set the CONSUL_BIND_INTERFACE
environment variable to define your local interface connected to your
router/internet.

Make sure the docker group has access to:

* ``/run/docker/plugins/`` directory with read/execution (``r-x``)
* ``/run/docker/plugins/btrfs.sock`` file with read/write (``rw-``)

Then::

    $ pushd buttervolume
    $ docker-compose up -d
    $ popd
    $ mkdir deploy
    $ docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

And you may have buttervolumeplugin/consul/caddy/haproxy on your personal host !

To deploy a website::

    $ docker-compose exec consul consul event -name=deploy '{"master": "localhost.localdomain", "branch": "master", "repo": "https://gitlab.example.com/hosting/foobar"}'

Possibly replace localhost.localdomain with the hostname of your development machine.

Troubleshooting
***************

Manually starting, stopping or building containers
--------------------------------------------------

If you need to manually manage compose projets on a cluster node, you should go
to the ~/deploy folder and run compose commands as usually.  The compose
project name is already set in the .env file during deployment because the name
of the folder contains the deployment date and does not correspond to the
compose project name.

Duplicate btrfs/local volumes after a reboot
--------------------------------------------

Sometimes after a reboot, docker volume ls shows some volume in both local and btrfs driver (docker volume ls).
This should probably be fixed by letting buttervolume start before all other containers.

To repair the volume, just do that:

sudo -s
cd /var/lib/docker/volumes/
for v in `docker volume ls| awk '{print $2}'|sort|uniq -d`; do mv $v $v.tmp && docker volume rm $v && mv $v.tmp $v; done

Then migrate to buttervolume >= 2.0

Caddyfile is wrong
------------------

Probably an error in the Caddyfile stored in the consul KV store.

Try to regenerate the Caddyfile or haproxy.cfg manually to detect the error::

    $ ssh node1 -p 4022
    $ cd cluster
    $ docker-compose exec --user consul consul sh
    $ cat /docker-entrypoint.sh
    $ /bin/consul-template -once -template="/consul/template/caddy/Caddyfile.ctmpl:/consul/template/caddy/Caddyfile:/reload_caddy.sh"

Also try to open the web ui to quickly check the deployed parameters::

    $ ssh -L 8500:localhost:8500 user@node1
    $ firefox localhost:8500
    - click on Key/Value → app
    - You can change values, it should trigger the recompute of the Caddyfile and haproxy.cfg if something changed in the resulting file.
    - WARNING if you make a syntax error the caddyfile won't be regenerated and you may block all future deployments, or even break all the cluster.


proxy protocol
--------------

`Proxy protocol <https://www.haproxy.org/download/1.8/doc/proxy-protocol.txt>`_
let send real client IP from the first packet header even it's an encrypted
connection (like https).

.. warning::

    send-proxy and accept-proxy are already set in haproxy.
    When setting ``send-proxy`` on haproxy configuration, the backend (the
    Caddy server) **has to** understand and accept the proxy protocol.
    (note: but in Caddy conf file once configured to listen to proxy protol
    that works even it received proper http / https)


Cahier de recette
-----------------


cas à tester:
* avec tout les serveurs ont accès à internet:
* l'actuel master n'a pas accès à git
* le futur master n'a pas d'accès git
* le send ou la remonté du volume plante

Projet vide (volume, snapshot, container, projet git)
1. démarrage d'un nouveau projet sur 1 master avec un réplicat
* nothing -> master
* nothing -> slave
* nothing -> nothing

2. inverse master / réplicat
* master -> slave
* slave -> master
* nothing -> nothing

3. relance la même commande (redéploie sur le meme service)
* master -> master
* slave -> slave
* nothing -> nothing

4. on passe sur le troisieme noeud sans réplicat
* master -> nothing
* slave -> nothing
* nothing -> master

Quoi vérifier:

* purges présentes
* service consul
* k/v store
* projet git présent/absent
* container présent/absent
* volumes docker présent/absent

transition

