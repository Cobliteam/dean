import os
import os.path
import shutil
from typing import AnyStr, AsyncGenerator, Callable, List, Union

from pathspec.pathspec import PathSpec

from .async import AsyncIteratorWrapper, delay


Path = Union[bytes, str]

INCLUDE_ALL = lambda path: True  # noqa


async def async_scandir(*args, **kwargs):
    async for entry in AsyncIteratorWrapper(os.scandir(*args, **kwargs)):
        yield entry


async def async_walk(root: Path, *, depth_first=True,
                     include: Callable[[Path], bool] = INCLUDE_ALL) \
        -> AsyncGenerator[Path, None]:

    dir_stack: List[Path] = []

    async for entry in async_scandir(root):
        path = entry.path
        if entry.is_dir():
            path += '/'

        if not include(path):
            continue

        yield path

        if entry.is_dir():
            if depth_first:
                async for path in async_walk(path, depth_first=depth_first,
                                             include=include):
                    yield path
            else:
                dir_stack.append(path)

    if not depth_first:
        for path in reversed(dir_stack):
            async for path in async_walk(path, depth_first=depth_first,
                                         include=include):
                yield path


def async_glob_pathspec(root: Path, patterns: PathSpec, exclude: bool = False,
                        **kwargs) \
        -> AsyncGenerator[Path, None]:
    def _include(path):
        return patterns.match_file(path) == (not exclude)

    return async_walk(root, include=_include, **kwargs)


async def async_copytree_pathspec(src: AnyStr, dest: AnyStr, **kwargs) -> None:
    kwargs['depth_first'] = True

    async for path in async_glob_pathspec(src, **kwargs):
        rel_path = os.path.relpath(path, start=src)
        src_path = path
        dest_path = os.path.join(dest, rel_path)

        if dest_path.endswith('/'):
            await delay(os.makedirs, dest_path, exist_ok=True)
        else:
            await delay(shutil.copyfile, src_path, dest_path)
