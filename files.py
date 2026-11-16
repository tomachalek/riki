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


def get_version_info(repo_path: str, path: str) -> RevisionInfo:
    """
    Obtains information about the last change of a file (as of the working
    directory's parent revision) via Mercurial Python API

    arguments:
    repo_path -- path to the Mercurial repository root
    path -- a file we want revision information about

    returns:
    revision info; default values if the file is not tracked or on error
    """
    from mercurial import ui, hg, encoding, error
    from mercurial.utils import dateutil

    def to_str(v: bytes) -> str:
        return v.decode('utf-8', errors='replace')

    rel_path = os.path.relpath(os.path.realpath(path), os.path.realpath(repo_path)).replace(os.sep, '/')
    try:
        # Mercurial stores metadata in UTF-8; make it return them unchanged regardless of the server locale
        encoding.encoding = b'utf-8'
        repo = hg.repository(ui.ui(), repo_path.encode())
        fctx = repo[b'.'][rel_path.encode()]
        ctx = repo[fctx.introrev()]  # the changeset which introduced the current file version
        return RevisionInfo(
            date=to_str(dateutil.datestr(ctx.date())),
            user=to_str(ctx.user()),
            changeset=f'{ctx.rev()}:{to_str(ctx.hex()[:12])}',
            tag=' '.join(to_str(t) for t in ctx.tags()) or None,
            summary=to_str(ctx.description().split(b'\n', 1)[0]))
    except error.LookupError:  # e.g. a new file not committed yet
        return RevisionInfo()
    except Exception as e:
        logging.getLogger(__name__).warning('Failed to fetch version info about [%s]: %s', path, e)
        return RevisionInfo()


def commit_file(repo_path: str, rel_path: str, message: str, user: Optional[str] = None) -> bool:
    """
    Commits a single file (adding it to the repository if it is new) via Mercurial Python API.

    arguments:
    repo_path -- path to the Mercurial repository root
    rel_path -- path of the file relative to the repository root
    message -- commit message
    user -- commit author; if None, Mercurial's configuration decides

    returns:
    True if a changeset was created, False if there was nothing to commit

    raises:
    mercurial.error.Abort (or another Mercurial exception) on failure
    """
    from mercurial import ui, hg, commands, encoding

    # make Mercurial independent of the server locale (e.g. 'C' in a container)
    encoding.encoding = b'utf-8'
    u = ui.ui.load()
    repo = hg.repository(u, repo_path.encode())
    opts = {'message': message.encode(), 'addremove': True}
    if user:
        opts['user'] = user.encode()
    u.pushbuffer(error=True)
    try:
        ret = commands.commit(u, repo, b'path:' + rel_path.encode(), **opts)
    finally:
        output = u.popbuffer()
    if output:
        logging.getLogger(__name__).info('hg commit [%s]: %s', rel_path, output.decode(errors='replace').strip())
    return not ret
