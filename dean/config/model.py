import os
import re
from enum import Enum
from typing import Any, Collection, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from dataclasses import dataclass

from .parser import parse


RepositoryType = Enum('RepositoryType', 'git')


class Commands(List[str]):
    pass


@dataclass
class Build:
    doc_root: str
    build: Optional[Commands] = None
    ignore: Optional[Collection[str]] = None


@dataclass
class Repository:
    url: str
    revision: Optional[str] = None
    skip_if_failed: bool = False
    type: RepositoryType = RepositoryType.git

    def clone_url(self):
        if re.match(r'^.+?@.+?:.+?$', self.url):  # SSH
            return self.url

        url_fields = urlsplit(self.url)
        if url_fields.scheme not in ('', 'file'):
            return self.url

        path = url_fields.path
        if path.startswith('/'):
            return self.url

        new_fields = list(url_fields)
        new_fields[0] = 'file'
        new_fields[2] = os.path.abspath(path)

        return urlunsplit(new_fields)


@dataclass
class Aggregate:
    paths: Dict[str, Repository]
    branches: Collection[str] = ('master',)
    prepare: Optional[Commands] = None
    build: Optional[Commands] = None
    deploy: Optional[Commands] = None


@dataclass
class Config:
    build: Optional[Build] = None
    aggregate: Optional[Aggregate] = None
    doc_branch: str = 'docs/{branch}'

    @classmethod
    def parse(cls, data: Any) -> 'Config':
        return parse(cls, data)
