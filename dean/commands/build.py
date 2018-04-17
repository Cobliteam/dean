import logging
import os
from functools import wraps
from typing import Callable, Optional

import click
from pathspec.pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from dean.config.model import Config, Repository
from dean.git import LocalRepository
from dean.util.async import click_async_cmd
from dean.util.file import async_copytree_pathspec
from dean.util.git import get_repo_branch_and_commit
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

    repo_info = await get_repo_branch_and_commit(src_dir)

    target_branch = repo_info.branch or build_options.branch
    if not target_branch:
        logger.error('Repository has a detached HEAD, and does not have a '
                     'checked-out branch. Please manually specify the '
                     'target branch to build')
        return 1

    repository = Repository(url=src_dir, revision=repo_info.commit)
    local_repository = LocalRepository(
        remote=repository, url=repository.url, path=src_dir)

    docs_branch = config.doc_branch.format(branch=repo_info.branch)

    async with AsyncTempDir() as tmp_dir:
        build_dir = os.path.join(tmp_dir, 'build')
        build_worktree = local_repository.get_worktree(
            revision=repo_info.commit, path=build_dir, detach=True,
            checkout=True)

        docs_dir = os.path.join(tmp_dir, 'docs')
        docs_worktree = local_repository.get_worktree(
            revision=docs_branch, path=docs_dir, detach=False, checkout=False)

        async with build_worktree:
            if config.build.build:
                builder = CommandRunner(config.build.build, cwd=build_worktree)
                await builder.run()

            ignore_patterns = parse_ignore_patterns(config.build.ignore)

            async with docs_worktree:
                doc_root = config.build.doc_root.lstrip('/')
                doc_path = os.path.join(build_worktree.path, doc_root)

                await async_copytree_pathspec(
                    src=doc_path, dest=docs_worktree.path,
                    patterns=ignore_patterns, exclude=True)
                import pdb; pdb.set_trace()

    return 0


@click.command()
@build_options
@click.pass_context
@click_async_cmd
async def build(ctx: click.Context, **kwargs):
    await _build(ctx, **kwargs)
