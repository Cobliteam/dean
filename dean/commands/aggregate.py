import asyncio
import logging
import os
import shutil
from functools import partial
from typing import Optional

import click

from dean.cli import main
from dean.config.model import Repository
from dean.repository_manager import RepositoryManager
from dean.util import click_async_cmd

from . import DeanContext


logger = logging.getLogger(__name__)


async def delay(f, *args, loop):
    await loop.run_in_executor(None, f, *args)


def dir_is_empty(path):
    return next(os.scandir(path), None) is None


async def git_copy_tree(*args, loop, **kwargs):
    kwargs['ignore'] = shutil.ignore_patterns('.git')
    call = partial(shutil.copytree, **kwargs)
    return (await delay(call, *args, loop=loop))


@main.command()
@click.option('--dest-dir', '-d',
              type=click.Path(dir_okay=True, file_okay=False, resolve_path=True,
                              writable=True),
              help='Destination directory to write aggregated docs into. '
                   'Must be empty.')
@click.option('--repo-dir', default='./.dean-repos',
              type=click.Path(dir_okay=True, file_okay=False, resolve_path=True,
                              writable=True),
              help='Directory to clone all repositories into')
@click.option('--jobs', '-j', default=0, type=int,
              help='Number of parallel jobs to run. Set to 0 to automatically '
                   'determine from number of CPUs.')
@click.option('--branch', '-b', type=str, default=None,
              help='Generate docs for this branch only')
@click.pass_obj
@click_async_cmd
async def aggregate(ctx: DeanContext, dest_dir: str, repo_dir: str, jobs: int,
                    branch: Optional[str]) -> int:
    if jobs == 0:
        jobs = 4

    os.makedirs(repo_dir, exist_ok=True)
    os.makedirs(dest_dir, exist_ok=True)

    if not ctx.config.aggregate:
        logger.warn(
            'No aggregation defined in configuration file, nothing to do')
        return 0

    if not dir_is_empty(dest_dir):
        logger.error('Destination directory must be empty')
        return 1

    branches = [branch] if branch else ctx.config.branches
    manager = RepositoryManager(repo_dir, jobs, loop=ctx.loop)

    async def process_repository(branch: str, path: str, repository: Repository):
        path = path.lstrip('/').format(branch=branch)
        dest_path = os.path.join(dest_dir, path)

        async with manager.checkout(repository) as local_repo:
            await git_copy_tree(local_repo.path, dest_path, loop=ctx.loop)

    def tasks():
        for branch in branches:
            for path, repository in ctx.config.aggregate.items():
                yield asyncio.ensure_future(
                    process_repository(branch, path, repository),
                    loop=ctx.loop)

    await asyncio.gather(*tasks(), loop=ctx.loop)

    return 0
