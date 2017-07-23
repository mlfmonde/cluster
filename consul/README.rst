Cluster handler
===============

handler.py is an event handler for consul watch.
See: https://www.consul.io/docs/agent/watches.html
Events are transmitted from one member to all other cluster members,
and each node handler should manage it accordingly.
It receives json through stdin, as a list of events.

Test
****

Run the handler tests with::

    $ python3 -m venv venv
    $ ./venv/bin/pip install PyYAML requests
    $ source ./venv/bin/activate
    $ ./handler.py

Normal mode
***********

From Consul (the expected way), just configure a watcher (see the docker-compose.yml of the consul docker).
Then consul will send the event to the handler through stdin

Using from the shell
********************

You can also use the handler manually to try:

deploying an app::

    $ handler.py deploy '{"target": "node1", "branch": "master", "repo": "https://gitlab.example.com/hosting/foobar"}'

destroying an app::

    $ handler.py destroy '{"branch": "master", "repo": "https://gitlab.example.com/hosting/foobar"}'

migrating volumes between two apps::

    $ handler.py migrate '{"target": {"branch": "preprod", "repo": "https://gitlab.example.com/hosting/foobar"}, "branch": "master", "repo": "https://gitlab.example.com/hosting/foobar"}'

In the latter case, if the target repository is not provided, it will use the source repository. The repo URL is used to identify the application in the cluster.
