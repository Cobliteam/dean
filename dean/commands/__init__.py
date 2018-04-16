import asyncio
from dataclasses import dataclass  # noqa

from dean.config.model import Config


@dataclass
class DeanContext:
    loop: asyncio.AbstractEventLoop
    config: Config
