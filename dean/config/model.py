from enum import Enum
from typing import Collection, Dict, Optional

from dataclasses import dataclass

from .parser import parse


@dataclass
class Build:
    project: str
    commands: Collection[str]
    branches: Collection[str] = ('master',)
    include: Collection[str] = ('docs/',)
    exclude: Collection[str] = ()


RepositoryType = Enum('RepositoryType', 'git')


@dataclass
class Repository:
    url: str
    revision: str = None
    type: RepositoryType = RepositoryType.git


@dataclass
class Aggregate:
    paths: Dict[str, Repository]


@dataclass
class Config:
    build: Optional[Build] = None
    aggregate: Optional[Aggregate] = None
    doc_branch: str = 'docs/{branch}'

    @classmethod
    def parse(cls, data):
        return parse(cls, data)
