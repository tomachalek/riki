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

import tantivy
from bs4 import BeautifulSoup
from markdown import markdown
import os
import re
import shutil
from markupsafe import Markup, escape
from appconf import Conf
import argparse
from typing import List, Dict, Any

"""
python3 search.py --data-dir /home/tomas/work/data/riki-data-test/ -x ./test-index
"""


class Fulltext:

    _index_path: str
    _index: tantivy.Index
    _schema: tantivy.Schema

    def __init__(self, index_path: str, recreate: bool = False):
        self._index_path = index_path
        self._schema = self._create_schema()
        if recreate and os.path.isdir(index_path):
            shutil.rmtree(index_path)
        self._open_index()

    def _create_schema(self) -> tantivy.Schema:
        schema_builder = tantivy.SchemaBuilder()
        # 'raw' = the whole path is a single term, which allows exact delete-by-path on update
        schema_builder.add_text_field("path", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("title", stored=True)
        schema_builder.add_text_field("body", stored=False)  # Don't store to save space
        schema_builder.add_text_field("tags", stored=True)
        return schema_builder.build()

    def _open_index(self):
        if os.path.exists(self._index_path) and os.listdir(self._index_path):
            self._index = tantivy.Index.open(self._index_path)
        else:
            os.makedirs(self._index_path, exist_ok=True)
            self._index = tantivy.Index(self._schema, path=self._index_path)


class FulltextSearcher(Fulltext):

    _data_dir: str

    def __init__(self, index_path: str, data_dir: str):
        super().__init__(index_path)
        self._data_dir = data_dir

    def _extract_snippet(self, text: str, query_terms: List[str], max_chars: int = 200) -> str:
        """
        Extract a snippet around the first occurrence of any query term.
        """
        text_lower = text.lower()
        query_terms_lower = [term.lower() for term in query_terms if term]

        best_pos = -1
        for term in query_terms_lower:
            pos = text_lower.find(term)
            if pos != -1 and (best_pos == -1 or pos < best_pos):
                best_pos = pos

        if best_pos == -1:
            # No match found, return beginning
            return text[:max_chars] + ('...' if len(text) > max_chars else '')

        # Calculate snippet boundaries
        start = max(0, best_pos - 50)
        end = min(len(text), best_pos + max_chars - 50)

        snippet = text[start:end]
        if start > 0:
            snippet = '...' + snippet
        if end < len(text):
            snippet = snippet + '...'

        return snippet

    def _highlight_terms(self, text: str, query_terms: List[str]) -> Markup:
        """
        Highlight query terms in the text snippet. The text is HTML-escaped,
        only the inserted <b> tags are kept as markup.
        """
        terms = sorted({t for t in query_terms if t}, key=len, reverse=True)
        if not terms:
            return escape(text)
        pattern = re.compile('|'.join(re.escape(t) for t in terms), re.IGNORECASE)
        parts = []
        last = 0
        for m in pattern.finditer(text):
            parts.append(escape(text[last:m.start()]))
            parts.append(Markup('<b>{}</b>').format(m.group()))
            last = m.end()
        parts.append(escape(text[last:]))
        return Markup('').join(parts)

    def search(self, q: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Search the index and return results with highlights.

        Args:
            q: Query string
            limit: Maximum number of results to return

        Returns:
            List of result dictionaries with path, title, tags, and highlight
        """
        if not q or not q.strip():
            return []

        searcher = self._index.searcher()
        query = self._index.parse_query(q, ["body", "title", "tags"])

        # Extract query terms for highlighting
        query_terms = [term.strip() for term in q.split() if term.strip()]

        results = searcher.search(query, limit)
        ans = []

        for score, doc_address in results.hits:
            doc = searcher.doc(doc_address)
            item = {}

            # Extract stored fields
            path_value = doc.get_first("path")
            title_value = doc.get_first("title")
            tags_value = doc.get_first("tags")

            if path_value:
                # Remove .md extension for display
                display_path = path_value.rsplit('.', 1)[0] if path_value.endswith('.md') else path_value
                item['path'] = display_path

                # Read the file to generate snippet
                full_path = os.path.join(self._data_dir, path_value)
                try:
                    with open(full_path, 'r', encoding='utf-8') as fr:
                        content = fr.read()
                        plain_text = extract_text_from_md(content)
                        snippet = self._extract_snippet(plain_text, query_terms)
                        item['highlight'] = self._highlight_terms(snippet, query_terms)
                except (IOError, UnicodeDecodeError):
                    item['highlight'] = None
            else:
                continue  # Skip if no path

            item['title'] = title_value if title_value else ''
            item['tags'] = tags_value if tags_value else ''

            ans.append(item)

        return ans


def extract_text_from_md(md_text: str) -> str:
    """Extract plain text from markdown content."""
    html = markdown(md_text)
    return ' '.join(BeautifulSoup(html, features='html.parser').find_all(string=True))


def extract_title_from_md(md_text: str) -> str:
    """Extract title (first H1) from markdown content."""
    lines = [x.strip() for x in md_text.split('\n')]
    for i, line in enumerate(lines):
        # Check for # Title syntax
        if line.startswith('# '):
            return line[2:].strip()
        # Check for underlined title
        next_line = lines[i + 1] if i + 1 < len(lines) else ''
        if line and next_line and all(c == '=' for c in next_line):
            return line
    return ''


class FulltextWriter(Fulltext):

    _writer: tantivy.IndexWriter

    def __enter__(self):
        # Use 50MB heap, single thread for simplicity
        self._writer = self._index.writer(heap_size=50_000_000, num_threads=1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._writer.commit()
        else:
            self._writer.rollback()
        self._writer.wait_merging_threads()

    def update_document(self, path: str, md_text: str):
        """
        Replace any indexed version of the document at the path with the new content.
        """
        self._writer.delete_documents_by_term("path", path)
        self.add_document(path, md_text)

    def add_document(self, path: str, md_text: str):
        """
        Add a document to the index.

        Args:
            path: Relative path to the file
            md_text: Markdown content of the file
        """
        text = extract_text_from_md(md_text)
        title = extract_title_from_md(md_text)

        # Extract tags from path segments, excluding 'index' and empty strings
        tags = ' '.join(x for x in path.rsplit('.', 1)[0].split('/') if x not in ('index', ''))

        doc = tantivy.Document()
        doc.add_text("path", path)
        doc.add_text("title", title)
        doc.add_text("body", text)
        doc.add_text("tags", tags)

        self._writer.add_document(doc)


def _is_text_file(fpath: str) -> bool:
    return fpath.endswith('.md') or fpath.endswith('.txt')


def index_recursive(data_root: str, rel_path: str, fulltext: FulltextWriter):
    """
    Recursively index all markdown and text files in a directory tree.

    Args:
        data_root: Root directory of the data
        rel_path: Relative path from root to current directory
        fulltext: FulltextWriter instance
    """
    full_path = os.path.join(data_root, rel_path)

    try:
        items = os.listdir(full_path)
    except (PermissionError, OSError) as e:
        print(f"Warning: Cannot access {full_path}: {e}")
        return

    for item in items:
        if item.startswith('.'):  # e.g. the .hg directory
            continue
        file_path = os.path.join(data_root, rel_path, item)

        if os.path.isfile(file_path) and _is_text_file(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as fr:
                    content = fr.read()
                    fulltext.add_document(os.path.join(rel_path, item), content)
                    print(f"Indexed: {os.path.join(rel_path, item)}")
            except (IOError, UnicodeDecodeError) as e:
                print(f"Warning: Cannot read {file_path}: {e}")
        elif os.path.isdir(file_path):
            index_recursive(data_root, os.path.join(rel_path, item), fulltext)


if __name__ == '__main__':
    if 'RIKI_CONF_PATH' in os.environ:
        conf_path = os.environ['RIKI_CONF_PATH']
    else:
        conf_path = os.path.realpath(os.path.join(os.path.dirname(__file__), 'config.json'))
    with open(conf_path) as fr:
        conf: Conf = Conf.from_json(fr.read())

    argparser = argparse.ArgumentParser(description="Markdown file indexer using Tantivy")
    argparser.add_argument(
        '-f', '--file', help="(re)index a single file located within the data dir")
    argparser.add_argument(
        '-x', '--index-dir', type=str, help="custom index directory")
    argparser.add_argument(
        '-d', '--data-dir', help="custom text data location")
    args = argparser.parse_args()

    index_dir = args.index_dir if args.index_dir else conf.search_index_dir
    data_dir = args.data_dir if args.data_dir else conf.data_dir

    print(f"Indexing files from: {data_dir}")
    print(f"Index location: {index_dir}")

    if args.file:
        rel_path = os.path.relpath(os.path.abspath(args.file), os.path.abspath(data_dir))
        with open(os.path.join(data_dir, rel_path), 'r', encoding='utf-8') as fr:
            md_content = fr.read()
        with FulltextWriter(index_dir) as fw:
            fw.update_document(rel_path, md_content)
        print(f"Updated: {rel_path}")
    else:
        # full reindex always starts from an empty index (no duplicates, up-to-date schema)
        with FulltextWriter(index_dir, recreate=True) as fw:
            index_recursive(data_dir, '', fw)

    print("Indexing complete!")
