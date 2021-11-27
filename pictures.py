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

import os
from dataclasses import dataclass
from PIL import Image
import PIL.ExifTags
from typing import Optional, Tuple
import hashlib


@dataclass
class PictureInfo:

    datetime: Optional[str] = None
    camera: Optional[str] = None
    orientation: Optional[str] = None
    light_source: Optional[str] = None
    exposure_time: Optional[str] = None
    scene_type: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    gps_latitude: Optional[str] = None
    gps_longitude: Optional[str] = None
    image_description: Optional[str] = 'No description'


def info_from_xmp(img: Image) -> Optional[PictureInfo]:
    try:
        xmp = img.getxmp()
        items = xmp['xmpmeta']['RDF']['Description']
        if items.get('Make') or items.get('Model'):
            camera = '{} {}'.format(items.get('Make'), items.get('Model', '-'))
        else:
            camera = None
        return PictureInfo(
            datetime=items.get('DateTimeOriginal'),
            camera=camera,
            exposure_time=items.get('ExposureTime'),
            gps_latitude=items.get('GPSAltitude'),
            gps_longitude=items.get('GPSTimeStamp'),
            image_description=None,
            image_width=img.size[0],
            image_height=img.size[1])
    except Exception as ex:
        return None


def info_from_exif(img: Image) -> Optional[PictureInfo]:
    try:
        raw_exif = img.getexif()
        if raw_exif is None:
            return PictureInfo()
        exif = dict((PIL.ExifTags.TAGS[k], v) for k, v in raw_exif.items() if k in PIL.ExifTags.TAGS)
        if exif.get('Make') or exif.get('Model'):
            camera = '{} {}'.format(exif.get('Make'), exif.get('Model', '-'))
        else:
            camera = None
        return PictureInfo(
            image_description=exif.get('ImageDescription'),
            datetime=exif.get('DateTime'),
            camera=camera,
            orientation=exif.get('Orientation'),
            light_source=exif.get('LightSource'),
            exposure_time=exif.get('ExposureTime'),
            scene_type=exif.get('SceneType'),
            image_width=img.size[0],
            image_height=img.size[1])
    except Exception as ex:
        # TODO log
        return None


def get_metadata(img: str) -> PictureInfo:
    img_o = Image.open(img)
    meta = info_from_xmp(img_o)
    if meta is None:
        meta = info_from_exif(img_o)
    if meta is None:
        meta = PictureInfo()
    return meta



def get_thumbnail_path(cache_dir: str, url_path: str, size: Tuple[int, int]) -> str:
    code = hashlib.md5(f'{url_path}-{size[0]}-{size[1]}'.encode()).hexdigest()
    return os.path.join(cache_dir, f'{code}.jpg')


def calc_size(img: PIL.Image, new_width):
    w, h = img.size
    return int(round(float(new_width) * h / w))


def get_resized_image(cache_dir: str, path: str, width: int, normalize: bool) -> str:
    img = Image.open(path)
    size = (int(width), calc_size(img, width))
    thumb_path = get_thumbnail_path(cache_dir, path, size)
    if not os.path.isfile(thumb_path):
        img.thumbnail(size, Image.ANTIALIAS)
        if img.size[0] < img.size[1] and normalize:
            img = img.crop((0, 0, size[0], int(round(200. * 3 / 4))))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(thumb_path, 'JPEG', quality=90)  # TODO
    return thumb_path