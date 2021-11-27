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

import web
import json
import os
import logging
from logging import handlers
from dataclasses import dataclass, field
from dataclasses_json import dataclass_json, LetterCase
from typing import List

import markdown
from jinja2 import Environment, FileSystemLoader, FileSystemBytecodeCache

import files
import pictures


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Conf:
    app_path: str
    data_dir: str
    log_path: str
    template_cache_dir: str
    picture_cache_dir: str
    hg_info_encoding: str
    markdown_extensions: List[str] = field(default_factory=lambda: [])
    app_name: str = field(default='Riki')


with open(os.path.realpath(os.path.join(os.path.dirname(__file__), 'config.json'))) as fr:
    conf: Conf = Conf.from_json(fr.read())

APP_NAME = conf.app_name
APP_PATH = conf.app_path


urls = (
    '', 'Index',
    '/', 'Index',
    '/_images', 'Images',
    '/page(/.+\\.txt)', 'Plain',
    '/page(/.+\.(jpg|JPG|jpeg|JPEG|png|PNG|gif|GIF))', 'Picture',
    '/page(/.*)?', 'Page',
    '/gallery(/.*)?', 'Gallery',
    '/_search', 'Search'
)


def setup_logger(path, debug=False):
    """
    Sets-up Python logger with file rotation

    Arguments:
    path -- where the log files will be written
    debug -- debug mode on/off (bool)
    """
    logger = logging.getLogger('')
    hdlr = handlers.RotatingFileHandler(path, maxBytes=(1 << 23), backupCount=50)
    hdlr.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
    logger.addHandler(hdlr)
    logger.setLevel(logging.INFO if not debug else logging.DEBUG)


def open_template(filename):
    cache = FileSystemBytecodeCache(conf.template_cache_dir)
    env = Environment(
        loader=FileSystemLoader(os.path.realpath(os.path.join(os.path.dirname(__file__), 'templates'))),
        bytecode_cache=cache)
    return env.get_template(filename)



setup_logger(str(conf.log_path))




def import_path(path):
    if path.find(APP_PATH) == 0:
        path = path[len(APP_PATH):]
    elif path[0] == '/':
        path = path[1:]
    return path


def load_markdown(path):
    """
    Loads a markdown file and returns an HTML code

    arguments:
    path -- path to a markdown file

    returns:
    a string containing output HTML
    """
    with open(path) as page_file:
        return markdown.markdown(
            page_file.read(),
            extensions=conf.markdown_extensions)


def extract_description(md_path):
    """
    extracts a text from an HTML code

    arguments:
    md_path -- path to a markdown file to be analyzed
    """
    import BeautifulSoup

    md_src = load_markdown(md_path)
    soup = BeautifulSoup.BeautifulSoup(md_src)
    h1 = soup.find('h1')
    if h1:
        h1_text = h1.text
    else:
        h1_text = ''
    h2 = soup.findAll(['h2', 'h3'])
    return [x.text for x in h2], h1_text


class Action(object):
    def __init__(self):
        self._wildcard_query = bool(int(web.cookies().get('wildcard_query', '0')))

    def set_wildcard_query(self, v):
        self._wildcard_query = v
        web.setcookie('wildcard_query', str(int(self._wildcard_query)), 3600 * 24 * 7)

    @property
    def data_dir(self):
        return conf.data_dir

    @staticmethod
    def get_current_dirname(path):
        ans = os.path.basename(path)
        if ans == 'index':
            ans = os.path.basename(os.path.dirname(path))
        return ans

    def _render(self, tpl_path, data, content_type='text/html'):
        template = open_template(tpl_path)
        web.header('Content-Type', content_type)
        values = dict(app_name=APP_NAME,
                      app_path=APP_PATH,
                      enable_search=False, # TODO
                      wildcard_query=self._wildcard_query)
        values.update(data)
        return template.render(**values)


class Index(object):
    """
    Homepage
    """
    def GET(self):
        web.seeother(f'{APP_PATH}page/index')


class Images(Action):
    """
    A page displaying list of all images

    TODO: this should be rather an attachment browser of some kind
    """
    def GET(self):
        images = files.list_files(self.data_dir, files.file_is_image, recursive=True)
        extended = []
        for img in images:
            extended.append(files.get_file_info(img, path_prefix=self.data_dir))
        return self._render('files.html', dict(files=extended))


class Plain(Action):
    def GET(self, path):
        page_fs_path = os.path.join(self.data_dir, path)
        web.header('Content-Type', 'text/plain')
        with open(page_fs_path, 'rb') as f:
            return f.read()


class Gallery(Action):

    def GET(self, path):
        path = import_path(path)
        gallery_fs_dir = os.path.dirname(os.path.join(self.data_dir, path))
        images = files.list_files(gallery_fs_dir, files.file_is_image, recursive=False)
        parent_dir = os.path.dirname(os.path.dirname(path))

        extended: List[files.FileInfo] = []
        for img in images:
            info = files.get_file_info(img, path_prefix=self.data_dir)
            info.metadata = pictures.get_metadata(img)
            extended.append(info)
        page_list = files.strip_prefix(
            files.list_files(
                gallery_fs_dir,
                os.path.isdir,
                recursive=False,
                include_dirs=True), self.data_dir)
        page_list = map(lambda x: (x, os.path.basename(x)), page_list)
        values = dict(
            files=extended,
            page_list=page_list,
            parent_dir=parent_dir,
            curr_dir_name=self.get_current_dirname(path))
        return self._render('gallery.html', values)


class Picture(Action):
    """
    Provides access to images
    """

    def GET(self, path, img_type):
        content_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'ico': 'image/x-icon'
        }
        fs_path = os.path.join(self.data_dir, import_path(path))
        args = web.input(width=None, normalize=False)
        width = args.width
        normalize = bool(int(args.normalize))
        if width is not None:
            fs_path = pictures.get_resized_image(
                cache_dir=conf.picture_cache_dir,
                path=fs_path,
                width=width,
                normalize=normalize)
        with open(fs_path, 'rb') as image:
            web.header('Content-Type', content_types.get(img_type, 'image/jpeg'))
            return image.read()


class Page(Action):
    """
    A riki page
    """
    def GET(self, path):
        if not path:
            raise web.seeother(f'{APP_PATH}page/index')

        path = import_path(path)
        page_fs_path = os.path.join(self.data_dir, path)

        if files.page_is_dir(page_fs_path):
            try:
                with open(os.path.join(page_fs_path, 'metadata.json'), 'rb') as fr:
                    metadata = json.load(fr)
            except IOError:
                metadata = {}
            if metadata.get('directoryType', 'page') == 'gallery':
                raise web.seeother(f'{APP_PATH}gallery/{path}/index')
            else:
                raise web.seeother(f'{APP_PATH}page/{path}/index')
        else:
            page_fs_path = f'{page_fs_path}.md'
            curr_dir = os.path.dirname(path)
            page_name = os.path.basename(path)

        # setup the directory information
        if curr_dir:
            parent_dir = os.path.dirname(curr_dir)
            curr_dir_fs = os.path.join(self.data_dir, curr_dir)
        else:
            curr_dir = u"\u2302"
            parent_dir = None
            curr_dir_fs = self.data_dir

        # transform the page
        if files.page_exists(page_fs_path):
            page_info = files.get_version_info(
                self.data_dir, page_fs_path, info_encoding=conf.hg_info_encoding)
            inner_html = load_markdown(page_fs_path)
            page_template = 'page.html'
        else:
            inner_html = ''
            page_info = ''
            page_template = 'dummy_page.html'

        page_list = files.strip_prefix(
            files.list_files(curr_dir_fs, None, recursive=False,
                include_dirs=True), self.data_dir)
        page_list = [(x, os.path.basename(x)) for x in page_list]
        logging.getLogger(__name__).warning('page_list: {}'.format(page_list))
        data = dict(html=inner_html,
                    page_list=page_list,
                    parent_dir=parent_dir,
                    page_info=page_info,
                    page_name=page_name,
                    curr_dir_name=self.get_current_dirname(curr_dir))
        return self._render(page_template, data)


class Search(Action):
    """
    Search results page
    """
    def GET(self):
        es = Elasticsearch(conf['fulltext']['serviceUrl'])
        if web.input(wildcard_query=None).wildcard_query:
            query = {
                "wildcard": {
                    "_all": web.input().query
                }
            }
            self.set_wildcard_query(True)
        else:
            query = {
                "multi_match": {
                    "query": web.input().query,
                    "operator": "and",
                    "fields": ["text", "pageName", "tags"]
                }
            }
            self.set_wildcard_query(False)
        res = es.search(index=conf['fulltext']['indexName'],
                        body={"query": query,
                              "fields": ["pageName", "path", "fsPath", "text"]})
        rows = []
        for a in res['hits']['hits']:
            fields = a['fields']

            fs_path = os.path.normpath('%s/%s.md' % (self.data_dir, fields['path'][0]))
            page_chapters, h1 = extract_description(fs_path)
            rows.append({
                'h1': h1 if h1 else fields['path'][0],
                'file': fields['path'][0],
                'chapters': page_chapters
            })
        values = dict(query=web.input().query, ans=rows)
        return self._render('search.html', values)

# web.config.debug = False
app = web.application(urls, globals(), autoreload=False)
application = app.wsgifunc()

if __name__ == "__main__":
    app = web.application(urls, globals())
    app.run()
