# Copyright 2021 Tomas Machalek <tomas.machalek@gmail.com>
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

from whoosh.fields import Schema, TEXT, KEYWORD, ID
from whoosh.analysis import StemmingAnalyzer
from whoosh import index, writing
from whoosh.qparser import MultifieldParser
from bs4 import BeautifulSoup
from markdown import markdown
import os
from appconf import Conf
import argparse

"""
python3 search.py --data-dir /home/tomas/work/data/riki-data-test/ -x ./test-index
"""


class Fulltext:

    _index_path: str

    _schema: Schema

    _index: index.FileIndex

    def __init__(self, index_path: str):
        self._index_path = index_path
        self._schema = Schema(
            path=ID(stored=True),
            body=TEXT(analyzer=StemmingAnalyzer()),
            tags=KEYWORD)
        self._open_index()

    def _open_index(self):
        if not index.exists_in(self._index_path):
            self._index = index.create_in(self._index_path, self._schema)
        else:
            self._index = index.open_dir(self._index_path, schema=self._schema)


class FulltextSearcher(Fulltext):

    _data_dir: str

    def __init__(self, index_path: str, data_dir: str):
        super().__init__(index_path)
        self._data_dir = data_dir

    def search(self, q: str):
        qp = MultifieldParser(['body', 'tags'], schema=self._schema)
        q_obj = qp.parse(q)
        ans = []
        with self._index.searcher() as srch:
            for hit in srch.search(q_obj):
                item = dict(hit)
                full_path = os.path.join(self._data_dir, hit['path'])
                with open(full_path) as fr:
                    full_text = fr.read()
                    item['highlight'] = hit.highlights('body', text=full_text)
                item['path'] = item['path'].rsplit('.', 1)[0]
                ans.append(item)
        return ans


def extract_text_from_md(md_text: str) -> str:
    return ' '.join(BeautifulSoup(markdown(md_text), features='lxml').findAll(text=True))


class FulltextWriter(Fulltext):

    _writer: writing.IndexWriter

    def __enter__(self):
        self._writer = self._index.writer()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._writer.commit()

    def add_document(self, path: str, md_text: str):
        text = extract_text_from_md(md_text)
        tags = ' '.join(x for x in path.rsplit('.', 1)[0].split('/') if x not in ('index', ''))
        self._writer.add_document(path=path, body=text, tags=tags)


def _is_text_file(fpath: str) -> bool:
    return fpath.endswith('.md') or fpath.endswith('.txt')


def index_recursive(data_root: str, rel_path: str, fulltext: FulltextWriter):
    full_path = os.path.join(data_root, rel_path)
    for item in os.listdir(full_path):
        file_path = os.path.join(data_root, rel_path, item)
        if os.path.isfile(file_path) and _is_text_file(file_path):
            with open(file_path) as fr:
                fulltext.add_document(os.path.join(rel_path, item), fr.read())
        elif os.path.isdir(file_path):
            index_recursive(data_root, os.path.join(rel_path, item), fulltext)


# TODO do we need this?
def extract_description(html: str):
    """
    extracts a text from an HTML code

    arguments:
    md_path -- path to a markdown file to be analyzed
    """
    soup = BeautifulSoup.BeautifulSoup(html)
    h1 = soup.find('h1')
    if h1:
        h1_text = h1.text
    else:
        h1_text = ''
    h2 = soup.findAll(['h2', 'h3'])
    return [x.text for x in h2], h1_text


if __name__ == '__main__':
    if 'RIKI_CONF_PATH' in os.environ:
        conf_path = os.environ['RIKI_CONF_PATH']
    else:
        conf_path = os.path.realpath(os.path.join(os.path.dirname(__file__), 'config.json'))
    with open(conf_path) as fr:
        conf: Conf = Conf.from_json(fr.read())
    argparser = argparse.ArgumentParser(description="Markdown file indexer")
    argparser.add_argument(
        '-f', '--file', help="a single file to index")
    argparser.add_argument(
        '-x', '--index-dir', type=str, help="custom index directory")
    argparser.add_argument(
        '-d', '--data-dir', help="custom text data location")
    args = argparser.parse_args()
    with FulltextWriter(args.index_dir if args.index_dir else conf.search_index_dir) as fw:
        index_recursive(args.data_dir if args.data_dir else conf.data_dir, '', fw)
