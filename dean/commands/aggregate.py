import asyncio
import logging
import os
from functools import wraps
from typing import AnyStr, Callable, Optional

import click
from pathspec.pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from dean.config.model import Config, Repository
from dean.git import RepositoryManager
from dean.util.async import click_async_cmd
from dean.util.file import async_copytree_pathspec, dir_is_empty
from . import AggregateOptions, CommandRunner


logger = logging.getLogger(__name__)


async def git_copy_tree(src: AnyStr, dest: AnyStr, **kwargs) -> None:
    patterns = PathSpec([GitWildMatchPattern('.git')])
    await async_copytree_pathspec(src, dest, patterns=patterns, exclude=True,
                                  **kwargs)


def aggregate_options(f: Callable) -> Callable:
    @click.option('--dest-dir', '-d',
                  type=click.Path(dir_okay=True, file_okay=False, resolve_path=True,
                                  writable=True),
                  help='Destination directory to write aggregated docs into. '
                       'Must be empty.')
    @click.option('--repo-dir', default='./.dean-repos',
                  type=click.Path(dir_okay=True, file_okay=False, resolve_path=True,
                                  writable=True),
                  help='Directory to clone all repositories into')
    @click.option('--jobs', '-j', default=None, type=int,
                  help='Number of parallel jobs to run. Set to 0 to automatically '
                       'determine from number of CPUs.')
    @click.option('--branch', '-b', type=str, default=None,
                  help='Generate docs for this branch only')
    @click.pass_context
    @wraps(f)
    def wrapper(ctx: click.Context, *args, dest_dir: str, repo_dir: str,
                jobs: int, branch: Optional[str], **kwargs):
        with ctx.scope(cleanup=False):
            ctx.obj = AggregateOptions(dest_dir=dest_dir, repo_dir=repo_dir,
                                       jobs=jobs, branch=branch)
            return f(*args, **kwargs)

    return wrapper


async def _aggregate(ctx: click.Context, **kwargs) -> int:
    config = ctx.find_object(Config)
    agg_opts = ctx.find_object(AggregateOptions)

    os.makedirs(agg_opts.repo_dir, exist_ok=True)
    os.makedirs(agg_opts.dest_dir, exist_ok=True)

    if not config.aggregate:
        logger.warn(
            'No aggregation defined in configuration file, nothing to do')
        return 0

    if not dir_is_empty(agg_opts.dest_dir):
        logger.error('Destination directory must be empty')
        return 1

    branches = config.aggregate.branches
    if agg_opts.branch:
        branches = [agg_opts.branch]

    manager = RepositoryManager(agg_opts.repo_dir, agg_opts.jobs)

    async def process_repository(branch: str, path: str, repository: Repository):
        path = path.lstrip('/').format(branch=branch)
        dest_path = os.path.join(agg_opts.dest_dir, path)

        async with manager.checkout(repository) as local_repo:
            await git_copy_tree(local_repo.path, dest_path)

    def repos():
        for branch in branches:
            for path, repository in config.aggregate.paths.items():
                yield asyncio.ensure_future(
                    process_repository(branch, path, repository))

    await asyncio.gather(*repos())
    if config.aggregate.build:
        env = {
            'REPO_DIR': agg_opts.repo_dir,
            'DEST_DIR': agg_opts.dest_dir
        }
        runner = CommandRunner(config.aggregate.build, env=env)
        await runner.run()

    return 0


@click.command()
@aggregate_options
@click.pass_context
@click_async_cmd
async def aggregate(ctx: click.Context, **kwargs):
    await _aggregate(ctx, **kwargs)
