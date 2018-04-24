#!/bin/bash

docker kill -s USR1 cluster_caddy_1 || docker restart cluster_caddy_1
