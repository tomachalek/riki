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

import markdown
from jinja2 import Environment, FileSystemLoader, FileSystemBytecodeCache

import files


urls = (
    '/', 'Index',
    '/_images', 'Images',
    '/page(/.+\.(jpg|jpeg|png|gif))', 'Image',
    '/page(/.*)?', 'Page',
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
    cache = FileSystemBytecodeCache(str(conf['templateCacheDir']))
    env = Environment(loader=FileSystemLoader(os.path.realpath('%s/templates' % os.path.dirname(__file__))),
                      bytecode_cache=cache)
    return env.get_template(filename)


conf = json.load(open('%s/config.json' % os.path.realpath(os.path.dirname(__file__))))
setup_logger(str(conf['logPath']))


def import_path(path):
    p = conf.get('appPath')
    if path.find(p) == 0:
        path = path[len(p):]
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
        return markdown.markdown(page_file.read().decode('utf-8'),
                                 extensions=conf.get('markdownExtensions', []))


def extract_text(node):
    """
    extracts a text from an HTML tree
    """
    # TODO indexing should be done from the original source (i.e. from the markup files)
    import BeautifulSoup
    ans = []
    for tag in node:
        if hasattr(tag, 'string') and tag.string:
            ans.append(tag.string)
        elif type(tag) is unicode or type(tag) is str:
            ans.append(tag)
        elif isinstance(tag, BeautifulSoup.Tag):
            if tag.name in ('div', 'p', 'table', 'tr', 'ul'):
                ans.append('...')
            ans += extract_text(tag)
    return ans


def extract_data(text):
    """
    extracts a text from an HTML code
    """
    # TODO indexing should be done from the original source (i.e. from the markup files)
    import BeautifulSoup
    soup = BeautifulSoup.BeautifulSoup(text)
    h1 = soup.find('h1')
    if h1:
        h1_text = h1.text
    else:
        h1_text = ''
    s = extract_text(soup)
    return ' '.join(s), h1_text


class Index(object):
    """
    Homepage
    """
    def GET(self):
        web.seeother("/page/index")


class Images(object):
    """
    A page displaying list of all images
    """
    def GET(self):
        data_path = str(conf['dataDir'])
        images = files.list_files(data_path, files.file_is_image, recursive=True)
        extended = []
        for img in images:
            extended.append(files.get_file_info(img, path_prefix=data_path))
        template = open_template('files.html')
        web.header('Content-Type', 'text/html')
        return template.render(appPath=str(conf['appPath']), files=extended)


class Image(object):
    """
    Provides images
    """
    def GET(self, path, img_type):
        content_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'ico': 'image/x-icon'
        }
        path = import_path(path)
        image_dir = '%s/%s' % (str(conf['dataDir']), path)

        with open(image_dir, 'rb') as image:
            web.header('Content-Type', content_types.get(img_type, 'text/plain'))
            return image.read()


class Page(object):
    """
    A riki page
    """
    def GET(self, path):
        if not path:
            raise web.seeother('/page/index')

        path = import_path(path)
        data_dir = str(conf['dataDir'])
        page_fs_path = '%s/%s' % (data_dir, path)

        if files.page_is_dir(page_fs_path):
            raise web.seeother('/page/%s/index' % path)
        else:
            page_fs_path = '%s.md' % page_fs_path
            curr_dir = os.path.dirname(path)

        if curr_dir:
            parent_dir = '%s' % os.path.dirname(curr_dir)
            curr_dir_fs = '%s/%s' % (data_dir, curr_dir)
        else:
            parent_dir = None
            curr_dir_fs = data_dir

        if files.page_exists(page_fs_path):
            page_info = files.get_version_info(data_dir, page_fs_path)
            inner_html = load_markdown(page_fs_path)
            page_template = 'page.html'
        else:
            inner_html = ''
            page_info = ''
            page_template = 'dummy_page.html'

        page_list = files.strip_prefix(files.list_files(curr_dir_fs, None,
                                                        recursive=False, include_dirs=True), data_dir)

        template = open_template(page_template)
        html = template.render(appPath=str(conf['appPath']),
                               html=inner_html,
                               page_list=page_list,
                               parent_dir=parent_dir,
                               page_info=page_info)
        web.header('Content-Type', 'text/html')
        return html


class Search(object):
    """
    Search results page
    """
    def GET(self):
        from whoosh import index
        from whoosh.qparser import QueryParser

        query = web.input().query
        ll_query = 'content:%s OR tags:%s' % (query, query)
        ix = index.open_dir(conf['fulltextIndexDir'])
        parser = QueryParser("content", ix.schema)
        myquery = parser.parse(ll_query)

        with ix.searcher() as searcher:
            ans = searcher.search(myquery)
            rows = []
            for a in ans:
                fs_path = os.path.normpath('%s/%s.md' % (conf['dataDir'], a['file']))
                page_text, h1 = extract_data(load_markdown(fs_path))
                a.text = a.highlights(fieldname='content', text=page_text)
                a.h1 = h1 if h1 else a['file']
                rows.append(a)
            template = open_template('search.html')
            web.header('Content-Type', 'text/html')
            html = template.render(appPath=str(conf['appPath']),
                                   query=query,
                                   ans=rows)
            return html


app = web.application(urls, globals(), autoreload=False)
application = app.wsgifunc()

if __name__ == "__main__":
    app = web.application(urls, globals())
    app.run()
