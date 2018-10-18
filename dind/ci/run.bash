#!/usr/bin/env bash
docker-compose exec ci run-contexts /tests/test_bind_relative_path.py -v -s
