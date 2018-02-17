#!/bin/bash
docker kill -s HUP cluster_haproxy_1 || docker restart cluster_haproxy_1

