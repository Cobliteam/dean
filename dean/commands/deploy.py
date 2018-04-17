import logging

from dean.cli import main
from dean.config.model import Config
from dean.util import click_async_cmd

from . import BuildOptions, CommandRunner, DeployOptions, pass_config, \
              with_build_options, with_deploy_options
from .build import _build


logger = logging.getLogger(__name__)


async def _deploy(config: Config, build_opts: BuildOptions,
                  deploy_opts: DeployOptions):
    if config.aggregate.deploy:
        await CommandRunner(config.aggregate.deploy).run()


@main.command()
@pass_config
@with_build_options
@with_deploy_options
@click_async_cmd
async def deploy(deploy_opts: DeployOptions, build_opts: BuildOptions,
                 config: Config, **kwargs) -> int:
    ret = await _build(build_opts, config)
    if ret != 0:
        return ret

    ret = await _deploy(deploy_opts, build_opts, config)
    if ret != 0:
        return ret

    return 0
