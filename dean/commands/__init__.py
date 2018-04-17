import asyncio
import logging
import os
from dataclasses import dataclass  # noqa
from functools import wraps
from typing import Callable, Optional

import click

from dean.config.model import Commands, Config
from dean.util import AsyncTempFile, async_subprocess_run, delay


logger = logging.getLogger(__name__)


@dataclass
class BuildOptions:
    dest_dir: str
    repo_dir: str
    jobs: int
    branch: Optional[str]


@dataclass
class DeployOptions:
    noop: str = ''


class CommandRunner:
    def __init__(self, commands: Commands,
                 loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.commands = commands
        self._loop = loop

    async def _run_command(self, command: str) -> None:
        if command.startswith('#!'):
            logger.debug('Running command as a shell script:\n%s',
                         command)
            async with AsyncTempFile(mode='w+', encoding='utf-8') as f:
                await f.write(command)
                await delay(os.fchmod, f.fileno(), 0o700)
                await f.close()

                await async_subprocess_run(f.name, stdout=None, loop=self._loop)
        else:
            logger.debug('Running command with shell: %s', command)
            await async_subprocess_run(command, stdout=None, shell=True,
                                       loop=self._loop)

    async def run(self):
        for command in self.commands:
            await self._run_command(command)


pass_config = click.make_pass_decorator(Config)


def with_build_options(f: Callable) -> Callable:
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
    def wrapper(ctx, *args, dest_dir, repo_dir, jobs, branch, **kwargs):
        with ctx.scope(cleanup=False):
            ctx.obj = BuildOptions(dest_dir=dest_dir, repo_dir=repo_dir,
                                   jobs=jobs, branch=branch)
            return f(ctx.obj, *args, **kwargs)

    return wrapper


def with_deploy_options(f: Callable) -> Callable:
    @click.pass_context
    @wraps(f)
    def wrapper(ctx, *args, **kwargs):
        with ctx.scope(cleanup=False):
            ctx.obj = DeployOptions()
            return f(ctx.obj, *args, **kwargs)

    return wrapper
