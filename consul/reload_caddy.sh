#!/bin/bash

# Le signal USR1 met caddy dans un état incorrect (à creuser)
#docker kill -s USR1 cluster_caddy_1 || docker restart cluster_caddy_1
docker restart cluster_caddy_1
