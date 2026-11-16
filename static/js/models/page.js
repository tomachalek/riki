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
define(['jquery', 'models/layout', 'katex', 'models/linkpreview'], function ($, layout, katex, linkPreview) {
    'use strict';

    var lib = {};

    function isExternalLink(link) {
        const url = $(link).attr('href') || '';

        return url.indexOf('http') === 0;
    }

    function applyKatex() {
        const maths = document.querySelectorAll('.arithmatex');
        for (let i = 0; i < maths.length; i++) {
            const tex = maths[i].textContent || maths[i].innerText;
            if (tex.startsWith('\\(') && tex.endsWith('\\)')) {
                katex.render(tex.slice(2, -2), maths[i], {'displayMode': false});

            } else if (tex.startsWith('\\[') && tex.endsWith('\\]')) {
                katex.render(tex.slice(2, -2), maths[i], {'displayMode': true});
            }
        }
    }

    /**
     * Turn a search query into a list of plain terms (mirrors the server-side
     * snippet highlighting - i.e. whitespace-separated words, with the query
     * syntax noise like quotes, +/- prefixes, field names and operators removed).
     */
    function parseSearchTerms(query) {
        const terms = [];
        query.split(/\s+/).forEach(function (t) {
            t = t.replace(/^[+-]/, '').replace(/^\w+:/, '').replace(/^["'(]+|["')]+$/g, '');
            if (t && ['AND', 'OR', 'NOT'].indexOf(t) === -1) {
                terms.push(t);
            }
        });
        // longer terms first so they win over their own substrings
        return terms.sort(function (a, b) { return b.length - a.length; });
    }

    function escapeRegExp(s) {
        return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    /**
     * Highlight (case-insensitive) occurrences of the searched terms
     * passed via the 'hl' URL argument and scroll to the first one.
     */
    function highlightSearchTerms() {
        const query = new URLSearchParams(window.location.search).get('hl');
        if (!query) {
            return;
        }
        const terms = parseSearchTerms(query);
        const root = document.querySelector('section.main');
        if (!terms.length || !root) {
            return;
        }
        const pattern = new RegExp(terms.map(escapeRegExp).join('|'), 'gi');
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                if (node.parentNode.closest('script, style, textarea, .katex, mark.search-hl')) {
                    return NodeFilter.FILTER_REJECT;
                }
                pattern.lastIndex = 0;
                return pattern.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
            }
        });
        // collect first - modifying the DOM while walking would confuse the walker
        const nodes = [];
        while (walker.nextNode()) {
            nodes.push(walker.currentNode);
        }
        nodes.forEach(function (node) {
            const text = node.nodeValue;
            const frag = document.createDocumentFragment();
            let last = 0;
            let m;
            pattern.lastIndex = 0;
            while ((m = pattern.exec(text)) !== null) {
                if (m.index > last) {
                    frag.appendChild(document.createTextNode(text.slice(last, m.index)));
                }
                const mark = document.createElement('mark');
                mark.className = 'search-hl';
                mark.textContent = m[0];
                frag.appendChild(mark);
                last = m.index + m[0].length;
            }
            if (last < text.length) {
                frag.appendChild(document.createTextNode(text.slice(last)));
            }
            node.parentNode.replaceChild(frag, node);
        });
        const first = root.querySelector('mark.search-hl');
        if (first) {
            first.scrollIntoView({block: 'center'});
        }
    }

    /**
     * @param {{appPath?: string, linkPreview?: boolean, linkCards?: boolean}} [conf]
     */
    lib.init = function (conf) {
        conf = conf || {};
        layout.init();
        $('section.main a').each(function () {
            if (isExternalLink(this)) {
                $(this).addClass('external');
                $(this).attr('target', '_blank');
            }
        });
        const root = document.querySelector('section.main');
        if (conf.linkPreview && root) {
            linkPreview.init(root, {appPath: conf.appPath || '/', linkCards: !!conf.linkCards});
        }
        applyKatex();
        highlightSearchTerms();
    };

    return lib;
});
