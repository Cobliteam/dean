import asyncio
import logging
import os
import shutil
import signal
import subprocess
import tempfile
from functools import partial, wraps
from signal import SIGHUP, SIGINT
from typing import Any, AsyncContextManager, Awaitable, Callable, IO, NewType, \
                   Optional, Sequence, Text, Tuple, TypeVar, Union, cast

import aiofiles
import click


T = TypeVar('T')
_TXT = Union[bytes, Text]
_FILE = Union[None, int, IO[Any]]
_LoopFactory = Callable[[], asyncio.AbstractEventLoop]

TempFile = NewType('TempFile', IO[Any])
TempDirPath = _TXT

logger = logging.getLogger(__name__)


class AsyncLoopSupervisor:
    def __init__(self, loop: asyncio.AbstractEventLoop,
                 timeout: Union[int, float] = 65,
                 signals: Sequence[signal.Signals] = (SIGINT, SIGHUP)) -> None:
        self.loop = loop
        self.timeout = timeout
        self.timed_out = False
        self._signals = list(signals)
        self._timeout_handle: Optional[asyncio.Handle] = None
        self._stop_handle: Optional[asyncio.Handle] = None

    def _set_signals(self, fn: Optional[Callable[..., Any]], *args: Any) \
            -> None:
        for sig in self._signals:
            if fn is None:
                self.loop.remove_signal_handler(sig)
            else:
                self.loop.add_signal_handler(sig, fn, *args)

    def _interrupt(self) -> None:
        self._set_signals(self._stop)

        self._timeout_handle = self.loop.call_later(
            self.timeout, self._stop, True)

        raise KeyboardInterrupt

    def _stop(self, timed_out: bool = False) -> None:
        if timed_out:
            self.timed_out = True

        self._set_signals(None)

        if self._timeout_handle:
            self._timeout_handle.cancel()

        self._stop_handle = self.loop.call_later(1, self.loop.stop)

        raise KeyboardInterrupt

    def supervise(self, run_until: Awaitable[T]) -> T:
        run_fut = asyncio.ensure_future(run_until, loop=self.loop)
        self._set_signals(self._interrupt)

        try:
            while True:
                try:
                    return self.loop.run_until_complete(run_fut)
                except KeyboardInterrupt:
                    run_fut.cancel()
        finally:
            self._set_signals(None)
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())

            if self._timeout_handle:
                self._timeout_handle.cancel()

            if self._stop_handle:
                self._stop_handle.cancel()

            self.loop.stop()


class AsyncTempDir(AsyncContextManager[TempDirPath]):
    def __init__(self, *, loop: Optional[asyncio.AbstractEventLoop] = None,
                 **kwargs) -> None:
        self._loop = loop
        self._tmp_kwargs = kwargs

        self._path: Optional[TempDirPath] = None

    async def __aenter__(self) -> TempDirPath:
        mkdtemp = partial(tempfile.mkdtemp, **self._tmp_kwargs)
        path = await delay(mkdtemp, loop=self._loop)
        self._path = cast(_TXT, path)
        return self._path

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._path:
            await delay(shutil.rmtree, self._path, loop=self._loop)
            self._path = None


class AsyncTempFile(AsyncContextManager[TempFile]):
    def __init__(self, suffix: Optional[str] = None,
                 prefix: Optional[str] = None, dir: Optional[str] = None,
                 text: bool = False,
                 loop: Optional[asyncio.AbstractEventLoop] = None,
                 **kwargs) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._tmp_kwargs = dict(suffix=suffix, prefix=prefix, dir=dir,
                                text=text)
        self._open_kwargs = kwargs
        kwargs.setdefault('mode', 'w+' if text else 'w+b')

        self._path: Optional[_TXT] = None
        self._file: Optional[Any] = None

    async def __aenter__(self) -> TempFile:
        mkstemp = partial(tempfile.mkstemp, **self._tmp_kwargs)
        fd, path = await delay(mkstemp, loop=self._loop)
        self._path = cast(_TXT, path)

        try:
            self._file = f = \
                await aiofiles.open(fd, loop=self._loop, **self._open_kwargs)
            f.name = str(path)
            return f
        except:  # noqa
            await self.close()
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._file:
            await self._file.close()
            self._file = None

        if self._path:
            await delay(os.unlink, self._path, loop=self._loop)
            self._path = None


async def delay(f: Callable[..., T], *args: Any,
                loop: Optional[asyncio.AbstractEventLoop] = None) -> T:
    loop = loop or asyncio.get_event_loop()
    return (await loop.run_in_executor(None, f, *args))


async def async_subprocess_run(
        program: _TXT,
        *args: _TXT,
        input: Optional[bytes] = None,
        stdout: _FILE = subprocess.PIPE,
        stderr: _FILE = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        limit: int = 2 ** 32,
        shell: bool = False,
        **kwargs) -> Tuple[Optional[bytes], Optional[bytes]]:

    loop = loop or asyncio.get_event_loop()
    cmd = [program]
    if shell:
        proc = await asyncio.create_subprocess_shell(
            program, stdout=stdout, stderr=stderr, loop=loop, limit=limit,
            **kwargs)
    else:
        cmd.extend(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=stdout, stderr=stderr, loop=loop,
            limit=limit, **kwargs)

    out, err = await proc.communicate(input)
    ret = await proc.wait()

    if ret != 0:
        raise subprocess.CalledProcessError(ret, cmd, output=out)

    return out, err


def click_async_cmd(f: Callable[..., Awaitable[int]],
                    loop_factory: _LoopFactory = asyncio.get_event_loop) \
        -> Callable[..., None]:
    @click.pass_context
    @wraps(f)
    def wrapper(ctx: click.Context, *args, **kwargs):
        try:
            loop = loop_factory()
            supervisor = AsyncLoopSupervisor(loop)
            ret = supervisor.supervise(f(*args, **kwargs))
            if ret:
                ctx.exit(ret)
        except Exception:
            logger.exception('Unexpected exception')
            ctx.exit(255)

    return wrapper
