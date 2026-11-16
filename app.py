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

import asyncio
import hashlib
import os
import re
import shutil
import sys
import tempfile
import threading
import logging
from urllib.parse import quote
from logging import handlers
from typing import Callable, Dict, List, Tuple, Optional, TypeVar
from dataclasses import dataclass
from dataclasses_json import DataClassJsonMixin, LetterCase, config

from aiohttp.web import View, Application, run_app
from aiohttp import web
import markdown
from jinja2 import Environment, FileSystemLoader, FileSystemBytecodeCache, select_autoescape
from markupsafe import Markup
import pymdownx.emoji

import files
import linkpreview
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

T = TypeVar('T')


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
logging.getLogger(__name__).info('using Riki configuration %s', conf_path)


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


LINK_CARDS_MARKER = re.compile(r'<!--\s*riki:link-cards\s*-->')


def load_markdown(path: str) -> Tuple[str, str]:
    """
    Loads a markdown file and returns an HTML code

    arguments:
    path -- path to a markdown file

    returns:
    a 2-tuple (output HTML, markdown source)
    """
    with open(path) as page_file:
        source = page_file.read()
    return markdown.markdown(
        source,
        extensions=conf.markdown_extensions,
        extension_configs=markdown_config), source


routes = web.RouteTableDef()


@dataclass
class DirMetadata(DataClassJsonMixin):

    dataclass_json_config = config(letter_case=LetterCase.CAMEL)['dataclasses_json']

    directory_type: Optional[str] = 'page'

    description: Optional[str] = None

    # render lists of external links as cards (see also LINK_CARDS_MARKER for a per-page setting)
    link_cards: bool = False


class ActionHelper:

    def __init__(self, conf: appconf.Conf, assets_url: Optional[str]):
        self._dir_metadata: Dict[str, DirMetadata] = {}
        self._cache = FileSystemBytecodeCache(conf.template_cache_dir) if conf.template_cache_dir else None
        self._assets_url = assets_url
        self._template_env: Environment = Environment(
            loader=FileSystemLoader(os.path.realpath(os.path.join(os.path.dirname(__file__), 'templates'))),
            bytecode_cache=self._cache,
            autoescape=select_autoescape(['html']),
            trim_blocks=True,
            lstrip_blocks=True)

    def response_html(self, template, data):
        values = {
            'app_name': APP_NAME,
            'app_path': APP_PATH,
            'enable_search': True,  # TODO
            'enable_editing': conf.enable_editing,
            'enable_link_preview': bool(conf.link_preview_cache_dir),
            **data,
        }
        template_object = self._template_env.get_template(template)
        return web.Response(text=template_object.render(values), content_type='text/html')

    def response_file(self, path: str):
        return web.FileResponse(path)

    def dir_metadata(self, page_fs_path: str) -> DirMetadata:
        try:
            dir_path = page_fs_path if files.page_is_dir(page_fs_path) else os.path.dirname(page_fs_path)
        except FileNotFoundError:
            if os.path.basename(page_fs_path) != 'index':  # 'index' is an acceptable virtual page
                raise
            dir_path = os.path.dirname(page_fs_path)
        if dir_path not in self._dir_metadata:
            try:
                with open(os.path.join(dir_path, 'metadata.json'), 'rb') as fr:
                    self._dir_metadata[dir_path] = DirMetadata.from_json(fr.read())
            except OSError:
                self._dir_metadata[dir_path] = DirMetadata()
        return self._dir_metadata[dir_path]


async def run_blocking(fn: Callable[[], T]) -> T:
    """
    Runs a blocking (file system, image processing, search) function
    in a worker thread so it does not block the event loop.
    """
    return await asyncio.get_running_loop().run_in_executor(None, fn)


class BaseAction(View):

    @property
    def _ctx(self) -> ActionHelper:
        return self.request.app[HELPER_KEY]

    def response_html(self, template, data):
        return self._ctx.response_html(template, data)

    def response_file(self, path: str):
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


@routes.view(r'/page/{path:.+\.(txt|pdf|json|xml|yml|yaml)}')
class Plain(Action):

    async def get(self):
        return self.response_file(os.path.join(self.data_dir, self.riki_path))


@routes.view(r'/page/{path:.+\.(jpg|JPG|jpeg|JPEG|png|PNG|gif|GIF)}')
class Picture(Action):
    """
    Provides access to images
    """

    async def get(self):
        return await run_blocking(self._get)

    def _get(self):
        fs_path = os.path.join(self.data_dir, self.riki_path)
        width_arg = self.url_arg('width')
        try:
            width = int(width_arg) if width_arg is not None else None
            normalize = bool(int(self.url_arg('normalize') or '0'))
        except ValueError:
            raise web.HTTPBadRequest(text='Invalid width or normalize argument') from None
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
        return await run_blocking(self._get)

    def _get(self):
        if not self.riki_path:
            raise web.HTTPSeeOther(f'{APP_PATH}page/index')

        page_fs_path = os.path.join(self.data_dir, self.riki_path)
        pelms = page_fs_path.rsplit('.', 1)
        page_suff = None if len(pelms) < 2 else pelms[-1]

        if self.dir_metadata.directory_type == 'gallery':
            raise web.HTTPSeeOther(f'{APP_PATH}gallery/{self.riki_path}/index')
        if files.page_is_dir(page_fs_path):
            if self.dir_metadata.directory_type == 'page':
                raise web.HTTPSeeOther(f'{APP_PATH}page/{self.riki_path}/index')
            raise web.HTTPServerError(text='Unknown page type')
        if page_suff and page_suff in appconf.RAW_FILES:
            with open(page_fs_path, 'rb') as fr:
                return web.Response(body=fr.read(), content_type=appconf.RAW_FILES[page_suff])

        page_fs_path = f'{page_fs_path}.md'
        curr_dir = os.path.dirname(self.riki_path)
        page_name = os.path.basename(self.riki_path)

        # setup the directory information
        if curr_dir:
            path_elms = path_dir_elms(curr_dir)
            curr_dir_fs = os.path.join(self.data_dir, curr_dir)
        else:
            path_elms = []
            curr_dir_fs = self.data_dir

        # transform the page
        dir_exists = files.page_is_dir(curr_dir_fs)
        status = 200
        link_cards = False
        if files.page_exists(page_fs_path):
            page_info = files.get_version_info(self.data_dir, page_fs_path)
            html, source = load_markdown(page_fs_path)
            inner_html = Markup(html)  # noqa: S704 - trusted wiki content
            link_cards = self.dir_metadata.link_cards or bool(LINK_CARDS_MARKER.search(source))
            page_template = 'page.html'
        elif page_name == 'index' and dir_exists:
            inner_html = ''
            page_info = files.RevisionInfo()
            page_template = 'dummy_page.html'
        else:
            inner_html = ''
            page_info = files.RevisionInfo()
            page_template = 'missing_page.html'
            status = 404

        data = {
            'html': inner_html,
            'page_list': self.generate_page_list(curr_dir_fs) if dir_exists else [],
            'path_elms': path_elms,
            'page_info': page_info,
            'page_name': page_name,
            'page_path': self.riki_path,
            'curr_dir_name': self.get_current_dirname(curr_dir),
            'new_page_dir': curr_dir,
            'link_cards': link_cards,
        }
        resp = self.response_html(page_template, data)
        resp.set_status(status)
        return resp


@routes.view('/_new')
class NewPage(Action):
    """
    Turns the "new page" form (directory + page name) into a redirect to the page editor
    """
    async def get(self):
        if not conf.enable_editing:
            raise web.HTTPForbidden(text='Page editing is disabled')
        directory = (self.url_arg('dir') or '').strip('/')
        name = (self.url_arg('name') or '').strip().strip('/')
        name = name.removesuffix('.md')
        if not name:
            raise web.HTTPSeeOther(f'{APP_PATH}page/{quote(directory)}' if directory else f'{APP_PATH}page/index')
        page_path = f'{directory}/{name}' if directory else name
        raise web.HTTPSeeOther(f'{APP_PATH}_edit/{quote(page_path)}?new=1')


@routes.view('/_images')
class Images(Action):
    """
    A page displaying list of all images

    """
    async def get(self):
        return await run_blocking(self._get)

    def _get(self):
        images = files.list_files(self.data_dir, files.file_is_image, recursive=True)
        extended = [files.get_file_info(img, path_prefix=self.data_dir) for img in images]
        return self.response_html('files.html', {'files': extended})


@routes.view('/gallery/{path:.*}')
class Gallery(Action):

    @staticmethod
    def get_num_files(path: str):
        return len(os.listdir(path)) - 1  # minus metadata.json which is required for a gallery page

    async def get(self):
        return await run_blocking(self._get)

    def _get(self):
        gallery_fs_dir = os.path.join(self.data_dir, self.riki_path)
        if files.page_is_dir(gallery_fs_dir):
            if self.dir_metadata.directory_type == 'page':
                raise web.HTTPSeeOther(f'{APP_PATH}page/{self.riki_path}/index')
            if self.dir_metadata.directory_type == 'gallery':
                raise web.HTTPSeeOther(f'{APP_PATH}gallery/{self.riki_path}/index')
            raise web.HTTPServerError(text='Unknown page type')
        if os.path.isfile(gallery_fs_dir):
            raise web.HTTPInternalServerError(text='Gallery directory malformed')
        if os.path.basename(gallery_fs_dir) != 'index':
            raise web.HTTPNotFound
        gallery_fs_dir = os.path.dirname(gallery_fs_dir)

        try:
            images = files.list_files(gallery_fs_dir, files.file_is_image, recursive=False)
        except FileNotFoundError:
            raise web.HTTPNotFound from None
        extended: List[files.FileInfo] = []

        for img in images:
            info = files.get_file_info(img, path_prefix=self.data_dir)
            info.metadata = pictures.get_metadata(img)
            extended.append(info)
        values = {
            'files': extended,
            'page_list': [],
            'path_elms': path_dir_elms(self.riki_path),
            'curr_dir_name': self.get_current_dirname(self.riki_path),
            'num_files': self.get_num_files(gallery_fs_dir),
            'description': self.dir_metadata.description,
        }
        return self.response_html('gallery.html', values)


def _content_hash(content: Optional[str]) -> str:
    return hashlib.sha256((content or '').encode('utf-8')).hexdigest()


def _read_page_source(fs_path: str) -> Optional[str]:
    try:
        with open(fs_path, 'r', encoding='utf-8', newline='') as fr:
            return fr.read()
    except FileNotFoundError:
        return None


def _write_page_source(fs_path: str, content: str):
    """
    Writes the file atomically (a reader never sees a half-written page)
    """
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(fs_path), prefix='.riki-edit-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as fw:
            fw.write(content)
        if os.path.exists(fs_path):
            shutil.copymode(fs_path, tmp_path)
        else:
            os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, fs_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# serializes page saving (file write + hg commit + index update)
_edit_lock = threading.Lock()


@routes.view('/_edit/{path:.*}')
class Edit(Action):
    """
    Raw markdown editor of a page. Saving a page commits it to the Mercurial
    repository and updates the fulltext index.
    """

    def _page_location(self) -> Tuple[str, str]:
        """
        Returns a normalized riki path and a validated filesystem path of the page's markdown file
        """
        if not conf.enable_editing:
            raise web.HTTPForbidden(text='Page editing is disabled')
        elms = [x for x in self.riki_path.split('/') if x]
        if not elms or any(x.startswith('.') for x in elms):
            raise web.HTTPBadRequest(text='Invalid page path')
        page_path = '/'.join(elms)
        data_root = os.path.realpath(self.data_dir)
        if files.page_is_dir(os.path.join(data_root, page_path)):
            raise web.HTTPSeeOther(f'{APP_PATH}_edit/{quote(page_path)}/index')
        fs_path = os.path.realpath(os.path.join(data_root, f'{page_path}.md'))
        if not fs_path.startswith(data_root + os.sep):
            raise web.HTTPBadRequest(text='Invalid page path')
        if self._ctx.dir_metadata(fs_path).directory_type != 'page':
            raise web.HTTPBadRequest(text='Only regular pages can be edited')
        return page_path, fs_path

    def _render(self, page_path: str, content: str, base_hash: str, message: str = '',
                error: Optional[str] = None, status: int = 200):
        curr_dir = os.path.dirname(page_path)
        resp = self.response_html('edit.html', {
            'page_path': page_path,
            'page_name': os.path.basename(page_path),
            'path_elms': path_dir_elms(curr_dir),
            'page_list': [],
            'content': content,
            'base_hash': base_hash,
            'message': message,
            'error': error,
        })
        resp.set_status(status)
        return resp

    async def get(self):
        return await run_blocking(self._get)

    def _get(self):
        page_path, fs_path = self._page_location()
        content = _read_page_source(fs_path)
        error = None
        if self.url_arg('new') and content is not None:
            error = 'A page with this name already exists - you are editing the existing page.'
        return self._render(page_path, content or '', _content_hash(content), error=error)

    async def post(self):
        form = await self.request.post()
        content = str(form.get('content', '')).replace('\r\n', '\n')
        message = str(form.get('message', '')).strip()
        base_hash = str(form.get('base_hash', ''))
        return await run_blocking(lambda: self._post(content, message, base_hash))

    def _post(self, content: str, message: str, base_hash: str):
        page_path, fs_path = self._page_location()
        if not message:
            return self._render(
                page_path, content, base_hash, message, error='Please enter a commit message.', status=400)

        with _edit_lock:
            original = _read_page_source(fs_path)
            current_hash = _content_hash(original)
            if current_hash != base_hash:
                return self._render(
                    page_path, content, current_hash, message, status=409,
                    error='The page has been changed by someone else in the meantime. Your text is preserved '
                          'below - submitting it again will overwrite the other changes.')
            if original != content:
                err = self._save(fs_path, original, content, message)
                if err:
                    return self._render(page_path, content, base_hash, message, error=err, status=500)
        raise web.HTTPSeeOther(f'{APP_PATH}page/{quote(page_path)}')

    def _save(self, fs_path: str, original: Optional[str], content: str, message: str) -> Optional[str]:
        """
        Writes, commits and indexes the page. Returns an error message on failure.
        """
        os.makedirs(os.path.dirname(fs_path), exist_ok=True)
        _write_page_source(fs_path, content)
        rel_path = os.path.relpath(fs_path, os.path.realpath(self.data_dir))
        try:
            files.commit_file(self.data_dir, rel_path, message, conf.hg_commit_user)
        except Exception as ex:
            logger.exception('failed to commit page %s', rel_path)
            # keep the working copy consistent with the repository
            if original is None:
                os.unlink(fs_path)
            else:
                _write_page_source(fs_path, original)
            # Mercurial errors carry bytes messages
            detail = getattr(ex, 'message', None) or (ex.args[0] if ex.args else None)
            detail = detail.decode(errors='replace') if isinstance(detail, bytes) else str(ex)
            return f'Failed to commit the page (nothing has been saved): {detail}'

        if conf.search_index_dir:
            try:
                with search.FulltextWriter(conf.search_index_dir) as fw:
                    fw.update_document(rel_path, content)
            except Exception:
                # the page itself is saved; the index can be rebuilt with search.py
                logger.exception('failed to update fulltext index for %s', rel_path)
        return None


@routes.view('/_search')
class Search(Action):
    """
    Search results page
    """
    async def get(self):
        return await run_blocking(self._get)

    def _get(self):
        query = self.url_arg('query') or ''
        if not conf.search_index_dir:
            raise web.HTTPNotFound(text='Search is not configured')
        rows = []
        if query:
            srch = search.FulltextSearcher(conf.search_index_dir, conf.data_dir)
            try:
                rows = srch.search(query)
            except ValueError as ex:  # tantivy reports malformed queries this way
                logger.info('invalid search query %r: %s', query, ex)
        return self.response_html('search.html', {'query': query, 'rows': rows})


@routes.view('/_preview')
class LinkPreviewData(BaseAction):
    """
    Preview metadata (title, description, image) of an external link, as JSON
    """
    async def get(self):
        service = self.request.app.get(PREVIEW_KEY)
        if service is None:
            raise web.HTTPNotFound(text='Link previews are not configured')
        url = self.url_arg('url') or ''
        try:
            preview = await service.get(url)
        except linkpreview.PreviewError as ex:
            raise web.HTTPBadRequest(text=str(ex)) from None
        img_url = f'{APP_PATH}_preview/img/'
        return web.json_response({
            'url': preview.url,
            'finalUrl': preview.final_url,
            'title': preview.title,
            'description': preview.description,
            'siteName': preview.site_name,
            'image': img_url + preview.image if preview.image else None,
            'icon': img_url + preview.icon if preview.icon else None,
            'error': preview.error,
        }, headers={'Cache-Control': 'private, max-age=3600'})


@routes.view('/_preview/img/{name}')
class LinkPreviewImage(BaseAction):

    async def get(self):
        service = self.request.app.get(PREVIEW_KEY)
        path = service.image_path(self.request.match_info['name']) if service else None
        if path is None:
            raise web.HTTPNotFound()
        resp = self.response_file(path)
        resp.headers['Cache-Control'] = 'public, max-age=604800'
        return resp


HELPER_KEY = web.AppKey('helper', ActionHelper)
PREVIEW_KEY = web.AppKey('link_preview', linkpreview.LinkPreviewService)

app = Application()
app.add_routes(routes)


async def setup_runtime(application: Application):
    application[HELPER_KEY] = ActionHelper(conf, assets_url=None)  # TODO
    if conf.link_preview_cache_dir:
        service = linkpreview.LinkPreviewService(
            conf.link_preview_cache_dir, allow_private_networks=conf.link_preview_allow_private)
        await service.start()
        application[PREVIEW_KEY] = service


async def cleanup_runtime(application: Application):
    service = application.get(PREVIEW_KEY)
    if service:
        await service.close()


app.on_startup.append(setup_runtime)
app.on_cleanup.append(cleanup_runtime)


async def factory():
    return app


if __name__ == '__main__':
    # developer mode - in production, static files are served by a proxy server (e.g. Nginx)
    app.router.add_static(
        '/static', os.path.realpath(os.path.join(os.path.dirname(__file__), 'static')), show_index=False)
    run_app(app, port=8080)
