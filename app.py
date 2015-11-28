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
import hashlib

import markdown
from jinja2 import Environment, FileSystemLoader, FileSystemBytecodeCache
from PIL import Image
import PIL.ExifTags
from elasticsearch import Elasticsearch

import files


urls = (
    '/', 'Index',
    '/_images', 'Images',
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
    cache = FileSystemBytecodeCache(str(conf['templateCacheDir']))
    env = Environment(loader=FileSystemLoader(os.path.realpath('%s/templates' % os.path.dirname(__file__))),
                      bytecode_cache=cache)
    return env.get_template(filename)


conf = json.load(open('%s/config.json' % os.path.realpath(os.path.dirname(__file__))))
setup_logger(str(conf['logPath']))

APP_NAME = conf.get('app_name', 'Riki')
APP_PATH = str(conf['appPath'])


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


def extract_data(md_path):
    """
    extracts a text from an HTML code
    """
    # TODO indexing should be done from the original source (i.e. from the markup files)
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


class Index(object):
    """
    Homepage
    """
    def GET(self):
        web.seeother("%spage/index" % APP_PATH)


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
        return template.render(app_name=APP_NAME,
                               app_path=APP_PATH,
                               files=extended)


class Gallery(object):

    @staticmethod
    def _get_exif(img):
        return dict((PIL.ExifTags.TAGS[k], v) for k, v in img._getexif().items() if k in PIL.ExifTags.TAGS)

    def GET(self, path):
        data_dir = str(conf['dataDir'])
        path = import_path(path)
        gallery_fs_dir = os.path.dirname('%s/%s' % (data_dir, path))
        images = files.list_files(gallery_fs_dir, files.file_is_image, recursive=False)
        parent_dir = os.path.dirname(os.path.dirname(path))

        extended = []
        for img in images:
            info = files.get_file_info(img, path_prefix=data_dir)
            exif = self._get_exif(Image.open(img))
            info['exif_datetime'] = exif.get('DateTime')
            info['exif_model'] = '%s (%s)' % (exif.get('Model'), exif.get('Make'))
            info['exif_orientation'] = exif.get('Orientation')
            info['exif_light_source'] = exif.get('LightSource')
            info['exif_exposure_time'] = exif.get('ExposureTime')
            info['exif_scene_type'] = exif.get('SceneType')
            info['exif_image_width'] = exif.get('ExifImageWidth')
            info['exif_image_height'] = exif.get('ExifImageHeight')
            extended.append(info)

        template = open_template('gallery.html')
        web.header('Content-Type', 'text/html')
        page_list = files.strip_prefix(files.list_files(gallery_fs_dir, os.path.isdir,
                                                        recursive=False, include_dirs=True), data_dir)
        return template.render(app_path=APP_PATH,
                               app_name=APP_NAME,
                               files=extended,
                               page_list=page_list,
                               parent_dir=parent_dir)


class Picture(object):
    """
    Provides images
    """
    @staticmethod
    def _get_thumbnail_path(url_path, size):
        code = hashlib.md5('%s-%s-%s' % (url_path, size[0], size[1])).hexdigest()
        return '%s/%s.jpg' % (conf['pictureCacheDir'], code)

    @staticmethod
    def _calc_size(img, new_width):
        w, h = img.size
        return int(round(float(new_width) * h / w))

    def GET(self, path, img_type):
        content_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'ico': 'image/x-icon'
        }
        fs_path = '%s/%s' % (str(conf['dataDir']), import_path(path))
        args = web.input(width=None, normalize=False)
        width = args.width
        normalize = bool(int(args.normalize))
        if width is not None:
            img = Image.open(fs_path)
            size = (int(width), self._calc_size(img, width))
            thumb_path = self._get_thumbnail_path(path, size)
            if not os.path.isfile(thumb_path):
                img.thumbnail(size, Image.ANTIALIAS)
                if img.size[0] < img.size[1] and normalize:
                    img = img.crop((0, 0, size[0], int(round(200. * 3 / 4))))
                img.save(thumb_path, "JPEG", quality=90)  # TODO
            fs_path = thumb_path
        with open(fs_path, 'rb') as image:
            web.header('Content-Type', content_types.get(img_type, 'image/jpeg'))
            return image.read()


class Page(object):
    """
    A riki page
    """
    def GET(self, path):
        if not path:
            raise web.seeother('%spage/index' % APP_PATH)

        path = import_path(path)
        data_dir = str(conf['dataDir'])
        page_fs_path = '%s/%s' % (data_dir, path)

        if files.page_is_dir(page_fs_path):
            try:
                metadata = json.load(open('%s/metadata.json' % page_fs_path, 'rb'))
            except IOError:
                metadata = {}
            if metadata.get('directoryType', 'page') == 'gallery':
                raise web.seeother('%sgallery/%s/index' % (APP_PATH, path))
            else:
                raise web.seeother('%spage/%s/index' % (APP_PATH, path))
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
        html = template.render(app_name=APP_NAME,
                               app_path=APP_PATH,
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
        es = Elasticsearch(conf['fulltext']['serviceUrl'])
        query = {
            "match": {"_all": web.input().query}
        }
        res = es.search(index=conf['fulltext']['indexName'],
                        body={"query": query,
                              "fields": ["pageName", "path", "fsPath", "text"]})
        rows = []
        for a in res['hits']['hits']:
            fields = a['fields']

            fs_path = os.path.normpath('%s/%s.md' % (conf['dataDir'], fields['path'][0]))
            page_chapters, h1 = extract_data(fs_path)
            rows.append({
                'h1': h1 if h1 else fields['path'][0],
                'file': fields['path'][0],
                'chapters': page_chapters
            })

        template = open_template('search.html')
        web.header('Content-Type', 'text/html')
        return template.render(app_name=APP_NAME,
                               app_path=APP_PATH,
                               query=web.input().query,
                               ans=rows)


app = web.application(urls, globals(), autoreload=False)
application = app.wsgifunc()

if __name__ == "__main__":
    app = web.application(urls, globals())
    app.run()
