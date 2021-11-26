/*
 * Copyright (C) 2014 Tomas Machalek <tomas.machalek@gmail.com>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Wiki-pages functionality
 */
define(['jquery', 'models/layout'], function ($, layout) {
    'use strict';

    var lib = {};

    function isExternalLink(link) {
        var url = $(link).attr('href') || '';

        return url.indexOf('http') === 0;
    }

    lib.init = function () {
        layout.init();
        $('section.main a').each(function () {
            if (isExternalLink(this)) {
                $(this).addClass('external');
                $(this).attr('target', '_blank');
            }
        });
    };

    return lib;
});