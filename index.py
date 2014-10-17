#!/usr/bin/env python

# Copyright 2014 Tomas Machalek <tomas.machalek@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
A command-line fulltext indexing utility based on whoosh library
"""

import argparse
import os
import json

from whoosh import index
from whoosh.fields import *


def get_files(path, pattern=None):
    """
    Lists files (non-recursively) at the specified path.

    arguments:
    path -- path of a directory where the searching starts
    pattern -- optional regex pattern file names must satisfy to be included

    returns:
    list of absolute file paths
    """
    if os.path.isfile(path):
        return [path],
    else:
        dict_path = os.path.realpath(path)
        ans = []
        for item in os.listdir(dict_path):
            file_path = '%s/%s' % (dict_path, item)
            if os.path.isdir(file_path):
                ans += get_files(file_path, pattern)
            elif not os.path.isfile(file_path) or (pattern and not re.match(pattern, item)):
                continue
            else:
                ans.append(file_path)
        return ans


def norm_path(path):
    """
    Normalizes a filesystem path

    arguments:
    path -- a path to normalize

    returns:
    a normalized path
    """
    p = os.path.normpath(path)
    srch = re.match(r'([a-zA-Z]):(\\.+)', p)
    if srch:
        p = '%s%s' % (p[0].lower(), p[1:])
    return p


def idx_norm_path(path, data_dir):
    """
    Normalize path for use as a fulltext entry

    arguments:
    path -- path to be normalized
    data_dir -- a prefix common to all the potential entries

    returns:
    normalized path

    TODO: this is quite redundant
    """
    if path.find(data_dir) == 0:
        idx_path = path[len(data_dir):]
        if idx_path[0] == os.sep:
            idx_path = idx_path[1:]
        idx_path = idx_path.replace(os.sep, '/')
    else:
        idx_path = os.path.basename(path)

    if idx_path.endswith('.md'):
        idx_path = idx_path[:-3]
    return idx_path


def delete_index(path):
    """
    Removes index files from a specified directory

    arguments:
    path -- index files location
    """
    for item in os.listdir(path):
        file_path = '%s/%s' % (path, item)
        os.unlink(file_path)
        print('deleted: %s' % file_path)


def index_file(path, data_dir, writer):
    data_dir = norm_path(data_dir)
    path = norm_path(path)

    with open(path) as f:
        idx_path = unicode(idx_norm_path(path, data_dir))
        s = f.read().decode('utf-8')
        print(idx_path)
        tags = idx_path.replace('/', ',')
        writer.add_document(file=idx_path, content=s, tags=tags)


if __name__ == '__main__':
    conf = json.load(open('./config.json'))
    argparser = argparse.ArgumentParser(description="Markdown file indexer")
    argparser.add_argument('file', metavar="FILE", help="data directory")
    argparser.add_argument('-n', '--new-index', const=True, default=False,
                           action='store_const', help="creates new index")
    args = argparser.parse_args()

    data_dir = conf['dataDir']

    if args.new_index:
        delete_index(conf['fulltextIndexDir'])
        schema = Schema(file=TEXT(stored=True),
                        content=TEXT,
                        tags=KEYWORD(stored=True, lowercase=True, commas=True))
        idx = index.create_in(conf['fulltextIndexDir'], schema)
    else:
        idx = index.open_dir(conf['fulltextIndexDir'])

    writer = idx.writer()

    text_files = get_files(args.file, r'.+\.md$')
    for tf in text_files:
        index_file(tf, data_dir, writer)

    writer.commit()
