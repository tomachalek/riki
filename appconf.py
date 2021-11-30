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
    hg_info_encoding: str
    search_index_dir: Optional[str] = None
    markdown_extensions: List[str] = field(default_factory=lambda: [])
    app_name: str = field(default='Riki')


def load_conf(path: str) -> Conf:
    with open(path) as fr:
        return Conf.from_json(fr.read())


ROUTES = (
    '', 'Index',
    '/', 'Index',
    '/_images', 'Images',
    '/page(/.+\\.txt)', 'Plain',
    '/page(/.+\.(jpg|JPG|jpeg|JPEG|png|PNG|gif|GIF))', 'Picture',
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