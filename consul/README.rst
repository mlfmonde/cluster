Cluster handler
===============

handler.py is an event handler for consul watch.
See: https://www.consul.io/docs/agent/watches.html
Events are transmitted from one member to all other cluster members,
and each node handler should manage it accordingly.
It receives json through stdin, as a list of events.

Test
****

Run the handler tests with, this require python>3.4 (maybe more??)::

    $ python3 -m venv venv
    $ source ./venv/bin/activate
    $ python setup develop
    $ pip install -r requirements.tests.txt
    $ nosetests -v

If you can't get python>3.4, you can test within the consul image
wich get python3.6, in consul directory::

    $ docker build -t consul .
    $ sudo docker run -it --rm --entrypoint "" \
        consul  bash -c "pip3 install -r requirements.tests.txt && nosetests -v"


Normal mode
***********

From Consul (the expected way), just configure a watcher (see the docker-compose.yml of the consul docker).
Then consul will send the event to the handler through stdin

Using from the shell
********************

You can also use the handler manually to try:

deploying an app::

    $ handler.py deploy '{"target": "node1", "branch": "master", "repo": "https://gitlab.example.com/hosting/foobar", "update": true}'

destroying an app::

    $ handler.py destroy '{"branch": "master", "repo": "https://gitlab.example.com/hosting/foobar"}'

migrating volumes between two apps::

    $ handler.py migrate '{"target": {"branch": "preprod", "repo": "https://gitlab.example.com/hosting/foobar"}, "branch": "master", "repo": "https://gitlab.example.com/hosting/foobar", "update": true}'

In the latter case, if the target repository is not provided, it will use the source repository. The repo URL is used to identify the application in the cluster.
