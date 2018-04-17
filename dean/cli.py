import asyncio
import logging
from typing import IO, cast

import click
import yaml

from dean.config.model import Config


@click.group()
@click.option('--debug/--no-debug', default=False,
              help='Enable debug logging')
@click.option('-c', '--config-file', default='./dean.yml',
              type=click.Path(exists=True, dir_okay=False, resolve_path=True,
                              readable=True))
@click.pass_context
def main(ctx: click.Context, debug: bool, config_file: str):
    logging.basicConfig(level=logging.INFO)
    if debug:
        logging.getLogger('dean').setLevel(logging.DEBUG)

    with click.open_file(config_file, encoding='utf-8') as f:
        unicode_f = cast(IO[str], f)
        config = Config.parse(yaml.safe_load(unicode_f))

    loop = asyncio.get_event_loop()
    ctx.obj = config


from dean.commands import build, deploy  # noqa
