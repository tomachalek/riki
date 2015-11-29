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
 * A functionality common to all the pages.
 */
define(['jquery', 'win'], function ($, win) {
    'use strict'

    function endsWith(s, suff) {
        return s.indexOf(suff) === s.length - suff.length;
    }

    var lib = {};

    lib.init = function () {

    };

    lib.selectText = function (element) {
        var elm = $(element),
            range,
            selection;

        if (win.document.body.createTextRange) {
            range = win.document.body.createTextRange();
            range.moveToElementText(elm.get(0));
            range.select();

        } else if (win.getSelection) {
            selection = win.getSelection();
            range = win.document.createRange();
            range.selectNodeContents(elm.get(0));
            selection.removeAllRanges();
            selection.addRange(range);
        }
    };

    lib.unselectText = function () {
        if (win.getSelection().removeAllRanges) {
            win.getSelection().removeAllRanges();

        } else if (win.document.selection) {
            win.document.selection.empty();
        }
    };


    return lib;
});