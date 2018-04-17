import asyncio
import logging
import signal
import subprocess
from functools import partial, wraps
from signal import SIGHUP, SIGINT
from typing import Any, Awaitable, AsyncIterator, Callable, IO, Iterable, \
                   Iterator, Optional, Sequence, Tuple, TypeVar, Union, cast

import click


T = TypeVar('T')
T_co = TypeVar('T_co', covariant=True)
_TXT = Union[bytes, str]
_FILE = Union[None, int, IO[Any]]
_LoopFactory = Callable[[], asyncio.AbstractEventLoop]

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


class AsyncIteratorWrapper(AsyncIterator[T_co]):
    def __init__(self, iterlike: Union[Iterator[T_co], Iterable[T_co]],
                 loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._iterator: Iterator[T_co] = iter(iterlike)

    def __aiter__(self) -> AsyncIterator[T_co]:
        return self

    def _next(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration

    async def __anext__(self) -> T_co:
        try:
            return (await delay(self._next, loop=self._loop))
        except StopIteration:
            raise StopAsyncIteration


async def delay(f: Callable[..., T], *args: Any,
                loop: Optional[asyncio.AbstractEventLoop] = None,
                **kwargs) -> T:
    loop = loop or asyncio.get_event_loop()
    ret = await loop.run_in_executor(None, partial(f, **kwargs), *args)
    return ret


async def async_subprocess_run(
        program: _TXT,
        *args: _TXT,
        input: Optional[_TXT] = None,
        stdout: _FILE = subprocess.PIPE,
        stderr: _FILE = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        limit: int = 2 ** 32,
        shell: bool = False,
        encoding: Optional[str] = None,
        **kwargs) -> Tuple[Optional[_TXT], Optional[_TXT]]:

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

    bytes_input: Optional[bytes] = None
    if input:
        if encoding:
            if not isinstance(input, str):
                raise TypeError('Input must be `str`')

            bytes_input = cast(str, input).encode(encoding)
        elif isinstance(input, bytes):
            bytes_input = cast(bytes, input)
        else:
            raise TypeError('Input must be `bytes`')

    out: _TXT
    err: _TXT
    out, err = await proc.communicate(bytes_input)
    if encoding:
        if out:
            out = out.decode(encoding, errors='surrogate_or_strict')
        if err:
            err = err.decode(encoding, errors='surrogate_or_strict')

    ret = await proc.wait()
    if ret != 0:
        raise subprocess.CalledProcessError(ret, cmd, output=out, stderr=err)

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
