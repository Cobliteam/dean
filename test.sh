#!/bin/sh

set -e

flake8 dean
pytest --cov=dean dean/test
