import logging
import os
from functools import wraps
from typing import Callable, Optional

import click
from pathspec.pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from dean.config.model import Config, Repository
from dean.git import GitAsyncClient, LocalRepository
from dean.util.async import click_async_cmd
from dean.util.file import async_copytree_pathspec
from dean.util.tempfile import AsyncTempDir
from . import BuildOptions, CommandRunner


logger = logging.getLogger(__name__)


def build_options(f: Callable) -> Callable:
    @click.option('--src-dir', '-d', default='.',
                  type=click.Path(dir_okay=True, file_okay=False,
                                  resolve_path=True, readable=True))
    @click.option('--branch', '-b', type=str, default=None,
                  help='Generate docs for the chosen branch only. If not '
                       'passed, will be detected from the Git repository')
    @click.pass_context
    @wraps(f)
    def wrapper(ctx: click.Context, *args, src_dir: str, branch: Optional[str],
                **kwargs):
        with ctx.scope(cleanup=False):
            ctx.obj = BuildOptions(src_dir=src_dir, branch=branch)
            return f(*args, **kwargs)

    return wrapper


def parse_ignore_patterns(content: Optional[str]) -> Optional[PathSpec]:
    if not content:
        return None

    return PathSpec.from_lines(GitWildMatchPattern, content.lines())


async def _build(ctx: click.Context, **kwargs) -> int:
    config = ctx.find_object(Config)
    build_opts = ctx.find_object(BuildOptions)
    src_dir = build_opts.src_dir

    git_client = GitAsyncClient(path=src_dir)
    target_branch = \
        (await git_client.get_current_branch()) or build_opts.branch

    if not target_branch:
        logger.error('Repository has a detached HEAD, and does not have a '
                     'checked-out branch. Please manually specify the '
                     'target branch to build')
        return 1

    commit = await git_client.get_head_commit()
    repository = Repository(url=src_dir, revision=commit)
    local_repository = LocalRepository(
        remote=repository, url=repository.url, path=src_dir,
        client=git_client.at_path(src_dir))

    docs_branch = config.doc_branch.format(branch=target_branch)

    async with AsyncTempDir() as tmp_dir:
        # Create the build worktree pointing to the chosen commit
        build_dir = os.path.join(tmp_dir, 'build')
        build_worktree = local_repository.get_worktree(
            revision=commit, path=build_dir, detach=True, checkout=True)

        # We initially create the docs worktree, which is mean to be completely
        # unrelated to the others from the HEAD, since we cannot create an
        # orphan branch without checking it out. So we create it with an useless
        # head and fix it up later
        docs_dir = os.path.join(tmp_dir, 'docs')
        docs_worktree = local_repository.get_worktree(
            revision=commit, path=docs_dir, detach=True, checkout=False)

        async with build_worktree, docs_worktree:
            if config.build.build:
                builder = CommandRunner(
                    config.build.build, cwd=build_worktree.path)
                await builder.run()

            await docs_worktree.client.checkout_branch(
                name=docs_branch, orphan=True)
            await docs_worktree.client.run_git('rm', '-rf', '.')

            doc_root = config.build.doc_root.lstrip('/')
            doc_path = os.path.join(build_worktree.path, doc_root)
            ignore_patterns = parse_ignore_patterns(config.build.ignore)

            await async_copytree_pathspec(
                src=doc_path, dest=docs_worktree.path,
                patterns=ignore_patterns, exclude=True)

            await docs_worktree.client.run_git(
                'add', '-A')

            await docs_worktree.client.run_git(
                'commit', '-m', 'Docs update')

    return 0


@click.command()
@build_options
@click.pass_context
@click_async_cmd
async def build(ctx: click.Context, **kwargs):
    await _build(ctx, **kwargs)
