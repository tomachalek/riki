# Copyright 2014 Tomas Machalek <tomas.machalek@gmail.com>
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import os
import logging
import re
from typing import List, Any, Optional
import datetime
from dataclasses import dataclass


@dataclass
class FileInfo:
    size: int
    mtime: int
    relpath: str
    metadata: Optional[Any] = None


@dataclass
class RevisionInfo:
    date: Optional[str] = None
    user: str = 'unknown'
    changeset: Optional[str] = None
    tag: Optional[str] = None
    summary: Optional[str] = None


def strip_prefix(path, prefix):
    return re.sub(r'\.md$', '', re.sub(f'{prefix}', '', path))


def page_exists(path):
    return os.path.isfile(path)


def page_is_dir(path) -> bool:
    """
    Tests whether a path corresponds to a directory

    arguments:
    path -- a path to a file

    returns:
    True if the path represents a directory else False
    """
    return os.path.isdir(path)


def file_is_page(filename) -> bool:
    """
    Tests whether a file corresponds to a Markdown wiki page.
    Only a suffix is tested.

    arguments:
    filename - a filename or a path to a file

    returns:
    True if the file has a md suffix else False
    """
    return filename.endswith('.md')


def file_is_image(filename) -> bool:
    """
    Tests whether a filename corresponds to a supported image (jpg, jpeg, ico, png, gif).
    File suffix is used (i.e. no content analysis is performed).

    arguments:
    filename -- filename or a path

    returns:
    True if file is image else False
    """
    return os.path.basename(filename).split('.')[-1].lower() in ('jpg', 'jpeg', 'ico', 'png', 'gif')


def get_file_info(path, path_prefix='') -> FileInfo:
    """
    Obtains information about a file - size, mtime and a relative path
    (according to the provided path_prefix).

    arguments:
    path -- file path
    path_prefix -- a path prefix we want to remove

    returns:
    a dictionary {'size': ..., 'mtime': ..., 'relpath': ...}
    """
    mdate = datetime.datetime.fromtimestamp(int(os.path.getmtime(path))).strftime('%Y-%m-%d %H:%M:%S')
    fsize = os.path.getsize(path)
    if fsize > 1e6:
        fsize = '%01.1fMB' % round(fsize / 1e6, 2)
    else:
        fsize = '%dKB' % round(fsize / 1e3)
    return FileInfo(
        size=fsize,
        mtime=mdate,
        relpath=path[len(path_prefix):] if path.find(path_prefix) == 0 else path)


def list_files(path, predicate=None, recursive=False, include_dirs=False) -> List[str]:
    """
    Lists files (non-recursively) at the specified path.

    arguments:
    path -- path of a directory where the searching starts
    pattern -- optional regex pattern file names must satisfy to be included

    returns:
    list of absolute file paths
    """
    ans = []

    def sort_key(p1):
        return int(os.path.isdir(os.path.join(path, p1)))

    for item in sorted(os.listdir(path), key=sort_key):
        if item.startswith('.'):
            continue
        abspath = '%s/%s' % (path, item)
        if os.path.isdir(abspath):
            if include_dirs:
                ans.append(abspath)
            if recursive:
                ans += list_files(abspath, predicate, recursive)
        elif not os.path.isfile(abspath) or (callable(predicate) and not predicate(item)):
            continue
        else:
            ans.append(abspath)
    return sorted(ans)


def get_version_info(repo_path: str, path: str, info_encoding: str) -> RevisionInfo:
    """
    Obtains information about a file via Mercurial Python API

    arguments:
    path -- a file we want revision information about
    info_encoding -- encoding used on data fetched from hg (system dependent)

    returns:
    a dictionary {'date': str, 'user': str, 'changeset': str, 'summary' : str}
    """
    from mercurial import ui, hg, commands

    ans = {}
    try:
        u = ui.ui()
        repo = hg.repository(u, repo_path.encode())
        u.pushbuffer()
        commands.log(u, repo, path.encode(), limit=1)
        output = u.popbuffer()
        for item in re.split(r'\n', output.decode()):
            srch = re.match(r'^(\w+):\s+(.+)$', item)
            if srch:
                v = srch.groups()[1]
                ans[srch.groups()[0]] = v if info_encoding.lower() == 'utf-8' else v.decode(info_encoding)
    except Exception as e:
        logging.getLogger(__name__).warning('Failed to fetch version info about [%s]: %s' % (path, e))
    rev_info = RevisionInfo(**ans)
    return rev_info
