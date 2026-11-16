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

from dataclasses import dataclass, field
from dataclasses_json import dataclass_json, LetterCase
from typing import List, Optional


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Conf:
    app_path: str
    data_dir: str
    log_path: str
    template_cache_dir: str
    picture_cache_dir: str
    search_index_dir: Optional[str] = None
    markdown_extensions: List[str] = field(default_factory=lambda: [])
    emoji_cdn_url: Optional[str] = None
    app_name: str = field(default='Riki')
    # no longer used (Mercurial metadata are always UTF-8), kept for compatibility with existing configs
    hg_info_encoding: str = 'utf-8'
    # Riki has no authentication - enable only if the access is restricted otherwise
    enable_editing: bool = False
    # Mercurial user for commits made via the editor (if None, hg's own configuration is used)
    hg_commit_user: Optional[str] = None
    # previews of external links (hover popups, link cards) - disabled if None
    link_preview_cache_dir: Optional[str] = None
    # allow fetching previews from loopback/private network addresses (e.g. home NAS, router);
    # note that anyone who can access Riki can then probe your local network via the preview service
    link_preview_allow_private: bool = False


def load_conf(path: str) -> Conf:
    with open(path) as fr:
        return Conf.from_json(fr.read())


ROUTES = (
    '', 'Index',
    '/', 'Index',
    '/_images', 'Images',
    '/page(/.+\\.txt)', 'Plain',
    r'/page(/.+\.(jpg|JPG|jpeg|JPEG|png|PNG|gif|GIF))', 'Picture',
    '/page(/.*)?', 'Page',
    '/gallery(/.*)?', 'Gallery',
    '/_search', 'Search'
)


RAW_FILES = {
    'pdf': 'application/pdf',
    'txt': 'text/plain',
    'json': 'application/json',
    'xml': 'text/xml',
    'yml': 'text/yaml',
    'yaml': 'text/yaml'
}