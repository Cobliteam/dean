import os
import subprocess

import pytest

from dean.config.model import Config, Repository


def build_repository(root):
    os.makedirs(root)

    subprocess.check_call(['git', 'init'], cwd=root)

    os.makedirs(os.path.join(root, 'docs'))
    with open(os.path.join(root, 'docs', 'README.md'), 'w') as f:
        f.write('Hello, world\n')

    subprocess.check_call(['git', 'checkout', '-b', 'docs/master'], cwd=root)
    subprocess.check_call(['git', 'add', '-A'], cwd=root)
    subprocess.check_call(['git', 'commit', '-m', 'Test Commit'], cwd=root)

    return Repository(type='git', url=str(root), revision='docs/master')


@pytest.fixture
def config(tmpdir):
    repo_names = ['a', 'b']
    paths = {}

    for name in repo_names:
        repo_dir = str(tmpdir.join(name))
        paths[repo_dir] = build_repository(repo_dir)

    return Config.parse({
        'aggregate': {
            'paths': paths
        }
    })


@pytest.mark.integration
def test_aggregate(config):
    assert config == {}
