import asyncio
import logging
import os
import shutil
import tempfile
from typing import AsyncContextManager, Optional, Union, cast

import aiofiles
from aiofiles.threadpool.binary import AsyncFileIO
from aiofiles.threadpool.text import AsyncTextIOWrapper

from .async import delay


TempFile = Union[AsyncFileIO, AsyncTextIOWrapper]
Path = Union[bytes, str]

logger = logging.getLogger(__name__)


class AsyncTempDir(AsyncContextManager[Path]):
    def __init__(self, *, loop: Optional[asyncio.AbstractEventLoop] = None,
                 **kwargs) -> None:
        self._loop = loop
        self._tmp_kwargs = kwargs

        self._path: Optional[Path] = None

    async def __aenter__(self) -> Path:
        path = await delay(tempfile.mkdtemp, loop=self._loop,
                           **self._tmp_kwargs)
        self._path = cast(TempFile, path)
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

        self._path: Optional[Path] = None
        self._file: Optional[TempFile] = None

    async def __aenter__(self) -> TempFile:
        fd, path = await delay(tempfile.mkstemp, loop=self._loop,
                               **self._tmp_kwargs)
        self._path = path

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
