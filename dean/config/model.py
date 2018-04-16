import os
import re
from enum import Enum
from typing import Any, Collection, Dict, Optional

from dataclasses import dataclass

from .parser import parse


@dataclass
class Build:
    project: str
    commands: Collection[str]
    include: Collection[str] = ('docs/',)
    exclude: Collection[str] = ()


RepositoryType = Enum('RepositoryType', 'git')


@dataclass
class Repository:
    url: str
    revision: str = None
    type: RepositoryType = RepositoryType.git




@dataclass
class Config:
    build: Optional[Build] = None
    aggregate: Optional[Dict[str, Repository]] = None
    branches: Collection[str] = ('master',)
    doc_branch: str = 'docs/{branch}'

    @classmethod
    def parse(cls, data: Any) -> 'Config':
        return parse(cls, data)
