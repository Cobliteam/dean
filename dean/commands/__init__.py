import asyncio
import logging
import os
from typing import Dict, Optional

from dataclasses import dataclass

from dean.config.model import Commands
from dean.util.async import async_subprocess_run, delay
from dean.util.tempfile import AsyncTempFile


logger = logging.getLogger(__name__)


@dataclass
class AggregateOptions:
    dest_dir: str
    repo_dir: str
    jobs: int
    branch: Optional[str]


@dataclass
class BuildOptions:
    src_dir: str
    branch: Optional[str] = None


class CommandRunner:
    def __init__(self, commands: Commands,
                 loop: Optional[asyncio.AbstractEventLoop] = None,
                 **kwargs) -> None:
        self.commands = commands
        self._kwargs = kwargs
        self._loop = loop

    async def _run_command(self, command: str) -> None:
        if command.startswith('#!'):
            logger.debug('Running command as a shell script:\n%s',
                         command)
            async with AsyncTempFile(mode='w+', encoding='utf-8') as f:
                await f.write(command)
                await delay(os.fchmod, f.fileno(), 0o700)
                await f.close()

                await async_subprocess_run(f.name, stdout=None, loop=self._loop,
                                           **self._kwargs)
        else:
            logger.debug('Running command with shell: %s', command)
            await async_subprocess_run(command, stdout=None, shell=True,
                                       loop=self._loop, **self._kwargs)

    async def run(self):
        for command in self.commands:
            await self._run_command(command)
