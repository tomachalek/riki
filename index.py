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
import re
import datetime
import hashlib


from elasticsearch import Elasticsearch


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


class Indexer(object):

    def __init__(self, es, index_name, type_name):
        self._es = es
        self._index_name = index_name
        self._type_name = type_name

    @staticmethod
    def _create_id(doc):
        return hashlib.sha1(json.dumps(doc)).hexdigest()

    def index_file(self, path, data_dir):
        data_dir = norm_path(data_dir)
        path = norm_path(path)

        with open(path) as f:
            idx_path = unicode(idx_norm_path(path, data_dir))
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
            s = f.read().decode('utf-8')
            tags = idx_path.split('/')
            doc = {
                'datetime': mtime,
                'pageName': tags[-1],
                'path': idx_path,
                'fsPath': path,
                'tags': tags,
                'text': s
            }
            res = es.index(index=self._index_name, doc_type=self._type_name,
                           id=self._create_id(doc), body=doc)
            #print(res)
            # TODO test for errors



if __name__ == '__main__':
    conf = json.load(open('./config.json'))
    argparser = argparse.ArgumentParser(description="Markdown file indexer")
    argparser.add_argument('-f', '--file', help="a single file to index")
    argparser.add_argument('-n', '--new-index', const=True, default=False,
                           action='store_const', help="creates new index")
    args = argparser.parse_args()

    data_dir = conf['dataDir']

    es = Elasticsearch(conf['fulltext']['serviceUrl'])

    if args.new_index:
        index_conf = json.load(open('./index.json'))
        es.indices.create(index=conf['fulltext']['indexName'],
                          ignore=400,
                          body=index_conf)

    indexer = Indexer(es=es, index_name=conf['fulltext']['indexName'], type_name='pages')
    text_files = get_files(data_dir, r'.+\.md$')
    for tf in text_files:
        indexer.index_file(tf, data_dir)
