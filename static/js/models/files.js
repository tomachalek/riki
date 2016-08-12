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

define(['jquery', 'fancybox', 'models/layout'], function ($, fancybox, layout) {
    'use strict';

    var lib = {};

    lib.init = function () {
        layout.init();

        $(".fancybox").fancybox();

        $('.file-list .file-path').on('click', function (evt) {
            var textElm = $(evt.target);

            if (!textElm.data('status') || textElm.data('status') === 0) {
                textElm.data('status', 1);
                layout.selectText(textElm);

            } else {
                textElm.data('status', 0);
                layout.unselectText();
            }
        });
    };

    return lib;
});