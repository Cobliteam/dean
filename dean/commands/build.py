import asyncio
import logging
import os
import shutil
from functools import partial

from dean.cli import main
from dean.config.model import Config, Repository
from dean.repository_manager import RepositoryManager
from dean.util import click_async_cmd, delay

from . import BuildOptions, CommandRunner, pass_config, with_build_options


logger = logging.getLogger(__name__)


def dir_is_empty(path):
    return next(os.scandir(path), None) is None


async def git_copy_tree(*args, loop=None, **kwargs):
    kwargs['ignore'] = shutil.ignore_patterns('.git')
    call = partial(shutil.copytree, **kwargs)
    return (await delay(call, *args, loop=loop))


async def _build(build_opts: BuildOptions, config: Config) -> int:
    os.makedirs(build_opts.repo_dir, exist_ok=True)
    os.makedirs(build_opts.dest_dir, exist_ok=True)

    if not config.aggregate:
        logger.warn(
            'No aggregation defined in configuration file, nothing to do')
        return 0

    if not dir_is_empty(build_opts.dest_dir):
        logger.error('Destination directory must be empty')
        return 1

    branches = config.aggregate.branches
    if build_opts.branch:
        branches = [build_opts.branch]

    manager = RepositoryManager(build_opts.repo_dir, build_opts.jobs)

    async def process_repository(branch: str, path: str, repository: Repository):
        path = path.lstrip('/').format(branch=branch)
        dest_path = os.path.join(build_opts.dest_dir, path)

        async with manager.checkout(repository) as local_repo:
            await git_copy_tree(local_repo.path, dest_path)

    def repos():
        for branch in branches:
            for path, repository in config.aggregate.paths.items():
                yield asyncio.ensure_future(
                    process_repository(branch, path, repository))

    await asyncio.gather(*repos())
    if config.aggregate.build:
        await CommandRunner(config.aggregate.build).run()

    return 0


@main.command()
@pass_config
@with_build_options
@click_async_cmd
async def build(build_opts: BuildOptions, config: Config, **kwargs) -> int:
    ret = await _build(build_opts, config)
    if ret != 0:
        return ret

    return 0
