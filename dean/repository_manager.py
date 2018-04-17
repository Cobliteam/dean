import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, AsyncContextManager, Awaitable, Dict, List, Optional, \
                   Set, TypeVar
from dataclasses import dataclass, field

from dean.config.model import Repository
from dean.util import async_subprocess_run, delay


T = TypeVar('T')

logger = logging.getLogger(__name__)


class GitAsyncBase:
    loop: asyncio.AbstractEventLoop

    def _make_dir_sync(self, path: str) -> None:
        if not os.path.isdir(path):
            logger.debug('Creating directory: %s', path)
            os.makedirs(path)

    async def make_dir(self, path: str) -> None:
        await delay(self._make_dir_sync, path, loop=self.loop)

    async def rm_dir(self, path: str) -> None:
        logger.info('Removing %s', path)
        await delay(shutil.rmtree, path, loop=self.loop)

    async def run_git(self, *args: str, **kwargs) -> Optional[str]:
        kwargs['cwd'] = self.path
        out, _ = await async_subprocess_run('git', *args, **kwargs)
        return out


@dataclass
class LocalRepository(GitAsyncBase):
    remote: Repository
    url: str
    path: str
    loop: asyncio.AbstractEventLoop

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock(loop=self.loop)
        self._cloned_fut: Optional[Awaitable[Any]] = None

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
                self._cloned_fut = \
                    asyncio.ensure_future(self._clone(), loop=self.loop)

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
    path: str
    loop: asyncio.AbstractEventLoop
    detach: bool = False

    def __post_init__(self):
        self._tmpdir = None
        self._created = False

    async def create(self) -> None:
        if self._created:
            return

        await self.repository.clone()
        await self.repository._add_worktree(
            self.path, self.revision, detach=self.detach)
        self._created = True

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


class _WorktreeRunner(AsyncContextManager[LocalWorktree]):
    def __init__(self, worktree: LocalWorktree, *,
                 semaphore: asyncio.BoundedSemaphore) -> None:
        self.when_done: asyncio.Future[None] = asyncio.Future()
        self._worktree = worktree
        self._semaphore = semaphore

    async def __aenter__(self) -> LocalWorktree:
        await self._semaphore.acquire()
        await self._worktree.create()
        return self._worktree

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._worktree.destroy()
        self._semaphore.release()
        if exc_val is not None:
            self.when_done.set_exception(exc_val)
        else:
            self.when_done.set_result(None)


@dataclass
class RepositoryManager:
    base_dir: str
    parallelism: int = 1
    loop: asyncio.AbstractEventLoop = \
        field(default_factory=asyncio.get_event_loop)

    def __post_init__(self):
        self._parallelism_sem = asyncio.BoundedSemaphore(self.parallelism)
        self._repos: Dict[str, LocalRepository] = {}

    def _get_local_repository(self, repository: Repository) -> LocalRepository:
        url = repository.url

        existing_repo = self._repos.get(url)
        if existing_repo:
            return existing_repo

        fname = re.sub(r'/+', '_', url)
        path = os.path.join(self.base_dir, fname)

        local_repo = LocalRepository(
            remote=repository, url=repository.clone_url(), path=path,
            loop=self.loop)
        self._repos[url] = local_repo
        return local_repo

    def checkout(self, repository: Repository) -> _WorktreeRunner:
        local_repo = self._get_local_repository(repository)
        worktree_path = tempfile.mkdtemp(prefix='worktree_', dir=self.base_dir)

        worktree = local_repo.get_worktree(path=worktree_path,
                                           revision=repository.revision)
        worktree_cm = _WorktreeRunner(worktree, semaphore=self._parallelism_sem)
        return worktree_cm
