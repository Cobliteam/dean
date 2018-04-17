import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from subprocess import CalledProcessError
from typing import Any, AsyncContextManager, Awaitable, Dict, Optional, \
                   TypeVar, Union

from dataclasses import dataclass, field, replace

from dean.config.model import Repository
from dean.util.async import async_subprocess_run, delay


T = TypeVar('T')
Path = Union[bytes, str]

logger = logging.getLogger(__name__)


@dataclass
class GitAsyncClient:
    path: str
    git_path: str = 'git'
    loop: asyncio.AbstractEventLoop = \
        field(default_factory=asyncio.get_event_loop)

    def _gen_args(self, kwargs):
        for arg_name, arg_val in kwargs.items():
            if arg_val is True:
                yield '--' + arg_name
            elif arg_val is False:
                yield '--no-' + arg_name
            else:
                yield '--{}={}'.format(arg_name, arg_val)

    def at_path(self, path: str) -> 'GitAsyncClient':
        return replace(self, path=path)

    async def run_git(self, *args: str, **kwargs) -> str:
        cmd_args = [*args, *self._gen_args(kwargs)]
        logger.debug('Running git command: %s', cmd_args)

        out, _ = await async_subprocess_run(
            self.git_path, *cmd_args, encoding='utf-8', cwd=self.path)
        return out.rstrip()

    async def get_symbolic_ref(self, ref: str = 'HEAD', **kwargs) \
            -> Optional[str]:
        try:
            out = await self.run_git(
                'symbolic-ref', ref, **kwargs)
            return out
        except CalledProcessError:
            return None

    async def get_current_branch(self) -> Optional[str]:
        return (await self.get_symbolic_ref('HEAD', short=True))

    async def rev_parse(self, revision: str, **kwargs) -> Optional[str]:
        try:
            out = await self.run_git(
                'rev-parse', '--quiet', revision, **kwargs)
            return out
        except CalledProcessError:
            return None

    async def get_head_commit(self) -> str:
        commit = await self.rev_parse('HEAD')
        if not commit:
            raise RuntimeError(
                'Directory `{}` does not seem to be a Git repository'.format(
                    self.path))

        return commit

    async def checkout_branch(self, name: str, force: bool = False,
                              reset: bool = False, orphan: bool = False,
                              **kwargs) -> None:
        existing_ref = await self.rev_parse(name)
        if existing_ref:
            await self.run_git('checkout', name, force=force)
            return

        if orphan:
            branch_flag = '--orphan'
        elif reset:
            branch_flag = '-B'
        else:
            branch_flag = '-b'

        await self.run_git('checkout', branch_flag, name, force=force, **kwargs)
        cur_branch = await self.get_current_branch()
        if cur_branch != name:
            raise RuntimeError(
                'Expected branch {} after checkout, got {}'.format(
                    name, cur_branch))

    async def add_worktree(self, path: str, revision: str = 'HEAD', **kwargs) \
            -> None:
        await self.run_git('worktree', 'add', path, revision, **kwargs)

    async def remove_worktree(self, path: str, **kwargs) -> None:
        await self.run_git('worktree', 'remove', path, **kwargs)

    async def clone(self, url: str, **kwargs) -> None:
        await self.run_git('clone', url, self.path, **kwargs)

    async def fetch(self, remote: Optional[str] = None,
                    ref: Optional[str] = None, **kwargs) -> None:
        def _gen_args():
            if remote:
                yield remote
                if ref:
                    yield ref

        await self.run_git('fetch', *_gen_args(), **kwargs)


@dataclass
class LocalRepository:
    remote: Repository
    url: str
    path: str
    client: GitAsyncClient

    def __post_init__(self) -> None:
        self._loop = self.client.loop
        self._lock = asyncio.Lock(loop=self._loop)
        self._cloned_fut: Optional[Awaitable[Any]] = None

    async def _clone(self) -> None:
        async with self._lock:
            await delay(os.makedirs, self.path, exist_ok=True, loop=self._loop)

            git_test_path = os.path.join(self.path, '.git')
            if not os.path.exists(git_test_path):
                logger.info('Cloning repository `%s` to `%s`', self.url,
                            self.path)

                await self.client.clone(self.url)
            else:
                logger.info('Updating repository `%s` in `%s`', self.url,
                            self.path)

                await self.client.fetch(tags=True)

    async def clone(self) -> None:
        async with self._lock:
            if not self._cloned_fut:
                self._cloned_fut = \
                    asyncio.ensure_future(self._clone(), loop=self._loop)

        await self._cloned_fut

    async def destroy(self) -> None:
        async with self._lock:
            await delay(shutil.rmtree, self.path, loop=self._loop)

    def get_worktree(self, *, path: str, **kwargs) -> 'LocalWorktree':
        client = self.client.at_path(path)
        return LocalWorktree(repository=self, client=client, path=path,
                             **kwargs)


@dataclass
class LocalWorktree(AsyncContextManager['LocalWorktree']):
    repository: LocalRepository
    revision: str
    path: str
    client: GitAsyncClient
    detach: bool = False
    checkout: bool = True

    def __post_init__(self):
        self._loop = self.client.loop
        self._tmpdir = None
        self._created = False

    async def create(self) -> None:
        if self._created:
            return

        await self.repository.clone()
        await self.repository.client.add_worktree(
            self.path, self.revision,
            detach=self.detach, checkout=self.checkout)
        self._created = True

    async def destroy(self) -> None:
        if self._created:
            try:
                await self.repository.client.remove_worktree(
                    self.path,force=True)
            except subprocess.CalledProcessError:
                logger.warn('Failed to clean up worktree %s', self.path)

            self._created = False

        if self._tmpdir:
            await delay(shutil.rmtree, self._tmpdir, loop=self._loop)
            self._tmpdir = None

    async def __aenter__(self) -> 'LocalWorktree':
        await self.create()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.destroy()


class _WorktreeRunner(AsyncContextManager[LocalWorktree]):
    def __init__(self, worktree: LocalWorktree, *,
                 semaphore: asyncio.BoundedSemaphore) -> None:
        self.when_done: asyncio.Future[None] = asyncio.Future()
        self._worktree = worktree
        self._semaphore = semaphore

    async def __aenter__(self) -> LocalWorktree:
        assert not self.when_done.done()

        await self._semaphore.acquire()
        await self._worktree.create()
        return self._worktree

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            await self._worktree.destroy()
            if exc_val is not None:
                self.when_done.set_exception(exc_val)
            else:
                self.when_done.set_result(None)
        finally:
            self._semaphore.release()


class RepositoryManager:
    def __init__(self, base_dir: str, parallelism: int = 1,
                 loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.base_dir = base_dir
        self._loop = loop or asyncio.get_event_loop()
        self._parallelism_sem = asyncio.BoundedSemaphore(parallelism)
        self._repos: Dict[str, LocalRepository] = {}

    def import_local_repository(self, local_repository: LocalRepository) \
            -> LocalRepository:
        url = local_repository.remote.url
        existing_repo = self._repos.get(url)
        if existing_repo:
            return existing_repo

        self._repos[url] = local_repository
        return local_repository

    def get_local_repository(self, repository: Repository) -> LocalRepository:
        existing_repo = self._repos.get(repository.url)
        if existing_repo:
            return existing_repo

        url = repository.url
        fname = re.sub(r'/+', '_', url)
        path = os.path.join(self.base_dir, fname)

        client = GitAsyncClient(path=path, loop=self._loop)
        local_repo = LocalRepository(
            remote=repository, url=repository.clone_url(), path=path,
            client=client)
        return self.import_local_repository(local_repo)

    def checkout(self, repository: Repository) -> _WorktreeRunner:
        local_repo = self.get_local_repository(repository)
        worktree_path = tempfile.mkdtemp(prefix='worktree_', dir=self.base_dir)

        worktree = local_repo.get_worktree(path=worktree_path,
                                           revision=repository.revision)
        runner = _WorktreeRunner(worktree, semaphore=self._parallelism_sem)
        return runner
