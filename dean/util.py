import asyncio
import subprocess


async def async_subprocess_run(program, *args, input=None,
                               stdout=subprocess.PIPE, stderr=None, loop=None,
                               limit=None, **kwargs):
    loop = loop or asyncio.get_event_loop()
    cmd = [program] + list(args)

    limit = limit or 2 ** 32
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=stdout, stderr=stderr, loop=loop, limit=limit, **kwargs)
    out, err = await proc.communicate(input)
    ret = await proc.wait()

    if ret != 0:
        raise subprocess.CalledProcessError(ret, cmd, output=out)

    return out, err
