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
import sys
import logging
from logging import handlers
from typing import List, Tuple, Optional
from dataclasses import asdict, dataclass
from dataclasses_json import dataclass_json, LetterCase

from aiohttp.web import View, Application, run_app
from aiohttp import web
import markdown
from jinja2 import Environment, FileSystemLoader, FileSystemBytecodeCache
import pymdownx.emoji

import files
import pictures
import search
import appconf


if 'RIKI_CONF_PATH' in os.environ:
    conf_path = os.environ['RIKI_CONF_PATH']
else:
    conf_path = os.path.realpath(os.path.join(os.path.dirname(__file__), 'config.json'))
conf = appconf.load_conf(conf_path)
APP_NAME = conf.app_name
APP_PATH = conf.app_path

logger = logging.getLogger('')


def setup_logger(path, debug=False):
    """
    Sets-up Python logger with file rotation

    Arguments:
    path -- where the log files will be written
    debug -- debug mode on/off (bool)
    """
    if path == '#stderr':
        hdlr = logging.StreamHandler(sys.stderr)
    elif path == '#stdout':
        hdlr = logging.StreamHandler(sys.stdout)
    else:
        hdlr = handlers.RotatingFileHandler(path, maxBytes=(1 << 23), backupCount=50)
    hdlr.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
    logger.addHandler(hdlr)
    logger.setLevel(logging.INFO if not debug else logging.DEBUG)


setup_logger(str(conf.log_path))
logging.getLogger(__name__).info(f'using Riki configuration {conf_path}')


markdown_config = {
    'pymdownx.emoji': {
        'emoji_index': pymdownx.emoji.twemoji,
        'emoji_generator': pymdownx.emoji.to_svg,
        'options': {
            'image_path': conf.emoji_cdn_url
        }
    },
    'pymdownx.arithmatex': {
        'generic': True,
        'preview': False
    }
}


def path_dir_elms(path: str) -> List[Tuple[str, str]]:
    items = [x for x in path.split('/') if x != '']
    cumul = []
    ans = []
    for elm in items:
        cumul.append(elm)
        ans.append((elm, '/'.join(cumul[:])))
    return ans


def load_markdown(path: str) -> str:
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
            extensions=conf.markdown_extensions,
            extension_configs=markdown_config)


routes = web.RouteTableDef()


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class DirMetadata:

    directory_type: Optional[str] = 'page'

    description: Optional[str] = None


class ActionHelper:

    def __init__(self, conf: appconf.Conf, assets_url: str):
        self._dir_metadata = {}
        self._cache = FileSystemBytecodeCache(conf.template_cache_dir) if conf.template_cache_dir else None
        self._assets_url = assets_url
        self._template_env: Environment = Environment(
            loader=FileSystemLoader(os.path.realpath(os.path.join(os.path.dirname(__file__), 'templates'))),
            bytecode_cache=self._cache,
            trim_blocks=True,
            lstrip_blocks=True)

    def response_html(self, template, data):
        values = dict(
            app_name=APP_NAME,
            app_path=APP_PATH,
            enable_search=True) # TODO
        values.update(data)
        template_object = self._template_env.get_template(template)
        return web.Response(text=template_object.render(values), content_type='text/html')

    def response_file(self, path: str):
        return web.FileResponse(path)

    def dir_metadata(self, page_fs_path: str) -> DirMetadata:
        try:
            dir_path = page_fs_path if files.page_is_dir(page_fs_path) else os.path.dirname(page_fs_path)
        except FileNotFoundError as ex:
            if os.path.basename(page_fs_path) == 'index':  # 'index' is an acceptable virtual page
                dir_path = os.path.dirname(page_fs_path)
            else:
                raise ex
        if dir_path not in self._dir_metadata:
            try:
                with open(os.path.join(dir_path, 'metadata.json'), 'rb') as fr:
                    self._dir_metadata[dir_path] = DirMetadata.from_json(fr.read())
            except IOError:
                self._dir_metadata[dir_path] = DirMetadata()
        return self._dir_metadata[dir_path]


class BaseAction(View):

    @property
    def _ctx(self) -> ActionHelper:
        return self.request.app['helper']

    def response_html(self, template, data):
        return self._ctx.response_html(template, data)

    def response_file(self, path: bytes):
        return self._ctx.response_file(path)

    @property
    def riki_path(self):
        return self.request.match_info['path']

    def url_arg(self, k):
        return self.request.rel_url.query.get(k)


class Action(BaseAction):

    @property
    def data_dir(self):
        return conf.data_dir

    @staticmethod
    def get_current_dirname(path):
        ans = os.path.basename(path)
        if ans == 'index':
            ans = os.path.basename(os.path.dirname(path))
        return ans

    def generate_page_list(self, curr_dir_fs):
        page_list = files.list_files(curr_dir_fs, None, recursive=False, include_dirs=True)
        return [(
                files.strip_prefix(x, self.data_dir),
                os.path.basename(files.strip_prefix(x, self.data_dir)),
                os.path.isdir(x)
            ) for x in page_list]

    @property
    def dir_metadata(self) -> DirMetadata:
        return self._ctx.dir_metadata(os.path.join(self.data_dir, self.riki_path))


@routes.view('/')
class Index(Action):
    """
    Homepage
    """
    async def get(self):
        raise web.HTTPSeeOther(f'{APP_PATH}page/index')


@routes.view('/page')
class PageNoSpec(View):

    async def get(self):
        raise web.HTTPSeeOther(f'{APP_PATH}page/index')


@routes.view('/page/{path:.+\.(txt|pdf|json|xml|yml|yaml)}')
class Plain(Action):

    async def get(self):
        return self.response_file(os.path.join(self.data_dir, self.riki_path))


@routes.view('/page/{path:.+\.(jpg|JPG|jpeg|JPEG|png|PNG|gif|GIF)}')
class Picture(Action):
    """
    Provides access to images
    """

    async def get(self):
        fs_path = os.path.join(self.data_dir, self.riki_path)
        width = self.request.rel_url.query.get('width')
        normalize = bool(int(self.request.rel_url.query.get('normalize', '0')))
        if width is not None:
            fs_path = pictures.get_resized_image(
                cache_dir=conf.picture_cache_dir,
                path=fs_path,
                width=width,
                normalize=normalize)
        return self.response_file(fs_path)


@routes.view('/page/{path:.*}')
class Page(Action):
    """
    A riki page
    """
    async def get(self):
        if not self.riki_path:
            raise web.HTTPSeeOther(f'{APP_PATH}page/index')

        page_fs_path = os.path.join(self.data_dir, self.riki_path)
        pelms = page_fs_path.rsplit('.', 1)
        page_suff = None if len(pelms) < 2 else pelms[-1]

        if self.dir_metadata.directory_type == 'gallery':
                raise web.HTTPSeeOther(f'{APP_PATH}gallery/{self.riki_path}/index')
        elif files.page_is_dir(page_fs_path):
            if self.dir_metadata.directory_type == 'page':
                raise web.HTTPSeeOther(f'{APP_PATH}page/{self.riki_path}/index')
            else:
                raise web.HTTPServerError('Unknown page type')
        elif page_suff and page_suff in appconf.RAW_FILES:
            with open(page_fs_path, 'rb') as fr:
                web.header('Content-Type', appconf.RAW_FILES[page_suff])
                return fr.read()
        else:
            page_fs_path = f'{page_fs_path}.md'
            curr_dir = os.path.dirname(self.riki_path)
            page_name = os.path.basename(self.riki_path)

        # setup the directory information
        if curr_dir:
            path_elms = path_dir_elms(curr_dir)
            curr_dir_fs = os.path.join(self.data_dir, curr_dir)
        else:
            curr_dir = ''
            path_elms = []
            curr_dir_fs = self.data_dir

        # transform the page
        if files.page_exists(page_fs_path):
            page_info = files.get_version_info(
                self.data_dir, page_fs_path, info_encoding=conf.hg_info_encoding)
            inner_html = load_markdown(page_fs_path)
            page_template = 'page.html'
        else:
            inner_html = ''
            page_info = files.RevisionInfo()
            page_template = 'dummy_page.html'

        data = dict(
            html=inner_html,
            page_list=self.generate_page_list(curr_dir_fs),
            path_elms=path_elms,
            page_info=page_info,
            page_name=page_name,
            curr_dir_name=self.get_current_dirname(curr_dir))
        return self.response_html(page_template, data)


@routes.view('/_images')
class Images(Action):
    """
    A page displaying list of all images

    """
    async def get(self):
        images = files.list_files(self.data_dir, files.file_is_image, recursive=True)
        extended = []
        for img in images:
            extended.append(files.get_file_info(img, path_prefix=self.data_dir))
        return self.response_html('files.html', dict(files=extended))


@routes.view('/gallery/{path:.*}')
class Gallery(Action):

    async def get_num_files(self, path: str):
        return len(os.listdir(path)) - 1 # minus metadata.json which is required for a gallery page

    async def get(self):
        gallery_fs_dir = os.path.join(self.data_dir, self.riki_path)
        if files.page_is_dir(gallery_fs_dir):
            if self.dir_metadata.directory_type == 'page':
                raise web.HTTPSeeOther(f'{APP_PATH}page/{self.riki_path}/index')
            elif self.dir_metadata.directory_type == 'gallery':
                raise web.HTTPSeeOther(f'{APP_PATH}gallery/{self.riki_path}/index')
            else:
                raise web.HTTPServerError('Unknown page type')
        elif os.path.isfile(gallery_fs_dir):
            raise web.HTTPInternalServerError('Gallery directory malformed')
        elif os.path.basename(gallery_fs_dir) == 'index':
            gallery_fs_dir = os.path.dirname(gallery_fs_dir)
        else:
            raise web.HTTPNotFound()

        try:
            images = files.list_files(gallery_fs_dir, files.file_is_image, recursive=False)
        except FileNotFoundError:
            raise web.HTTPNotFound()
        extended: List[files.FileInfo] = []

        for img in images:
            info = files.get_file_info(img, path_prefix=self.data_dir)
            info.metadata = pictures.get_metadata(img)
            extended.append(info)
        values = dict(
            files=extended,
            page_list=[],
            path_elms=path_dir_elms(self.riki_path),
            curr_dir_name=self.get_current_dirname(self.riki_path),
            num_files=await self.get_num_files(gallery_fs_dir),
            description=self.dir_metadata.description)
        return self.response_html('gallery.html', values)


@routes.view('/_search')
class Search(Action):
    """
    Search results page
    """
    async def get(self):
        srch = search.FulltextSearcher(conf.search_index_dir, conf.data_dir)
        rows = srch.search(self.url_arg('query'))
        values = dict(query=self.url_arg('query'), rows=rows)
        return self.response_html('search.html', values)


app = Application()
app.add_routes(routes)

async def setup_runtime(app):
    app['helper'] = ActionHelper(conf, assets_url=None)  # TODO

app.on_startup.append(setup_runtime)

async def factory():
    return app

if __name__ == '__main__':
    app.update(asdict(conf))
    run_app(app, port='8080')
