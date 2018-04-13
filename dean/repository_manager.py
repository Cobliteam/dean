import asyncio
import logging
import os
import random
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Awaitable, Callable, Optional, T

from dataclasses import dataclass, field

from dean.config.model import Repository
from dean.util import async_subprocess_run


logger = logging.getLogger(__name__)


class GitAsyncBase:
    def _make_dir_sync(self, path: str) -> None:
        if not os.path.isdir(path):
            logger.debug('Creating directory: %s', path)
            os.makedirs(path)

    async def delay(self, f: Callable[..., T], *args: Any) -> T:
        return (await self.loop.run_in_executor(None, f, *args))

    async def make_dir(self, path: str) -> None:
        await self.delay(self._make_dir_sync, path)

    async def rm_dir(self, path: str) -> None:
        logger.info('Removing %s', path)
        await self.delay(shutil.rmtree, path)

    async def run_git(self, *args: str, **kwargs) -> Optional[str]:
        kwargs['cwd'] = self.path
        out, _ = await async_subprocess_run('git', *args, **kwargs)
        return out


@dataclass
class LocalRepository(GitAsyncBase):
    url: str
    path: str
    loop: asyncio.AbstractEventLoop

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock(loop=self.loop)
        self._cloned_fut = None

    async def _clone(self) -> None:
        async with self._lock:
            await self.make_dir(self.path)

            git_test_path = os.path.join(self.path, 'packed-refs')
            if not os.path.exists(git_test_path):
                logger.info('Cloning repository `%s` to `%s`', self.url,
                            self.path)

                await self.run_git(
                    'clone', '--bare', self.url, self.path)
            else:
                logger.info('Updating repository `%s` in `%s`', self.url,
                            self.path)

                await self.run_git('fetch', '--tags')

    async def clone(self) -> None:
        async with self._lock:
            if not self._cloned_fut:
                self._cloned_fut = asyncio.Task(self._clone(), loop=self.loop)

        await self._cloned_fut

    async def destroy(self) -> None:
        async with self._lock:
            await self.rm_dir(self.path)

    async def _add_worktree(self, path, revision, detach=False) -> None:
        detach_args = ['--detach'] if detach else []
        rev = revision or 'HEAD'
        async with self._lock:
            await self.run_git('worktree', 'add', *detach_args, path, rev)

    async def _remove_worktree(self, path) -> None:
        async with self._lock:
            await self.run_git('worktree', 'remove', '--force', path)

    def get_worktree(self, **kwargs) -> 'LocalWorktree':
        kwargs['repository'] = self
        kwargs['loop'] = self.loop
        return LocalWorktree(**kwargs)


@dataclass
class LocalWorktree(GitAsyncBase):
    repository: LocalRepository
    revision: str
    loop: asyncio.AbstractEventLoop
    path: Optional[str] = None
    detach: bool = False

    def __post_init__(self):
        self._tmpdir = None
        self._created = False

    async def _checkout(self) -> None:
        await self.repository._add_worktree(
            self.path, self.revision, detach=self.detach)
        self._created = True

    async def create(self) -> None:
        await self.repository.clone()

        if not self.path:
            self._tmpdir = \
                await self.delay(tempfile.mkdtemp)
            self.path = os.path.join(self._tmpdir, 'worktree')

        await self._checkout()

    async def destroy(self) -> None:
        if self._created:
            try:
                await self.repository._remove_worktree(self.path)
            except subprocess.CalledProcessError:
                logger.warn('Failed to clean up worktree %s', self.path)

            self._created = False

        if self._tmpdir:
            await self.rm_dir(self._tmpdir)
            self._tmpdir = None

        self.path = None


@dataclass
class RepositoryManager:
    base_dir: str
    parallelism: int = 1
    loop: asyncio.AbstractEventLoop = \
        field(default_factory=asyncio.AbstractEventLoop)

    def __post_init__(self):
        self._parallelism_sem = asyncio.BoundedSemaphore(self.parallelism)
        self._repos = {}
        self._worktrees = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        for worktree in self._worktrees:
            await worktree.destroy()

    def add(self, repository: Repository) -> LocalWorktree:
        url = repository.url

        local_repo = self._repos.get(url)
        if not local_repo:
            fname = re.sub(r'/+', '_', url)
            path = os.path.join(self.base_dir, fname)
            local_repo = self._repos.setdefault(
                url, LocalRepository(url=url, path=path, loop=self.loop))

        worktree_path = tempfile.mkdtemp(prefix='worktree_', dir=self.base_dir)
        worktree = local_repo.get_worktree(
            path=worktree_path,
            revision=repository.revision)
        self._worktrees.append(worktree)

    def process(self, callback: Callable[[Repository], Awaitable[T]]) \
            -> asyncio.Future:
        async def _process(worktree):
            async with self._parallelism_sem:
                await worktree.create()
                result = await callback(worktree.repository)
                return result

        tasks = [_process(wt) for wt in self._worktrees]
        return asyncio.gather(*tasks, loop=self.loop)


if __name__ == '__main__':
    async def process_repo(repository):
        repo_name = repository.url.split('/')[-1]
        sys.stdout.write('Processing: {}\n'.format(repo_name))
        await asyncio.sleep(random.uniform(1, 5))
        sys.stdout.write('Done: {}\n'.format(repo_name))

    async def run():
        # with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir = os.path.abspath('.repo-test')

        try:
            os.makedirs(tmp_dir)
        except FileExistsError:
            pass

        async with RepositoryManager(tmp_dir, 100, loop=loop) as manager:
            for i in range(1, 11):
                for _ in range(100):
                    path = os.path.abspath('repos/{}'.format(i))
                    repo = Repository(path)
                    manager.add(repo)
            await manager.process(process_repo)

    logging.basicConfig(level=logging.INFO)
    loop = asyncio.get_event_loop()

    def sigint_handler():
        run_all.cancel()

    loop.add_signal_handler(signal.SIGINT, sigint_handler)
    run_all = asyncio.ensure_future(run())
    try:
        loop.run_until_complete(run_all)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
