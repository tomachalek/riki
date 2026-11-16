/*
 * Copyright (C) 2026 Tomas Machalek <tomas.machalek@gmail.com>
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
 * Previews of external links:
 *  - a popup shown when hovering an external link
 *  - "link cards" - lists (and standalone paragraphs) of external links rendered as a grid of cards
 *
 * All the data come from Riki's /_preview service (which fetches and caches them server-side).
 * Note: fetched metadata are untrusted - they are inserted via textContent only.
 */
define([], function () {
    'use strict';

    const MAX_PARALLEL = 4;
    const HOVER_DELAY_MS = 400;
    const MAX_PARAGRAPH_NOTE_LEN = 200;

    let appPath = '/';
    const cache = new Map();
    const queue = [];
    let running = 0;

    // ---------------- data loading ----------------------

    function runNext() {
        while (running < MAX_PARALLEL && queue.length > 0) {
            running += 1;
            queue.shift()();
        }
    }

    /**
     * Load preview data (cached, with limited parallelism; urgent requests - i.e. hover - go first)
     */
    function getPreview(url, urgent) {
        if (!cache.has(url)) {
            cache.set(url, new Promise(function (resolve) {
                const job = function () {
                    fetch(appPath + '_preview?url=' + encodeURIComponent(url))
                        .then(function (resp) { return resp.ok ? resp.json() : null; })
                        .catch(function () { return null; })
                        .then(function (data) {
                            running -= 1;
                            resolve(data);
                            runNext();
                        });
                };
                if (urgent) {
                    queue.unshift(job);

                } else {
                    queue.push(job);
                }
                runNext();
            }));
        }
        return cache.get(url);
    }

    // ---------------- DOM helpers -----------------------

    function el(tag, className, text) {
        const elm = document.createElement(tag);
        if (className) {
            elm.className = className;
        }
        if (text) {
            elm.textContent = text;
        }
        return elm;
    }

    function hostname(url) {
        try {
            return new URL(url).hostname.replace(/^www\./, '');

        } catch (e) {
            return url;
        }
    }

    function hostHue(host) {
        let h = 0;
        for (let i = 0; i < host.length; i++) {
            h = (h * 31 + host.charCodeAt(i)) % 360;
        }
        return h;
    }

    function hasPreview(data) {
        return data && (data.title || data.description || data.image);
    }

    /**
     * A thumbnail box - an image if available, otherwise a colored box with the site's initial
     */
    function fillThumb(thumb, url, data) {
        thumb.textContent = '';
        if (data && data.image) {
            const img = el('img');
            img.loading = 'lazy';
            img.alt = '';
            img.addEventListener('load', function () {
                // logos and other near-square images would be badly cropped
                if (img.naturalWidth / img.naturalHeight < 1.4) {
                    img.classList.add('contain');
                }
            });
            img.src = data.image;
            thumb.appendChild(img);
            thumb.classList.remove('placeholder');

        } else {
            const host = hostname(url);
            thumb.classList.add('placeholder');
            thumb.style.backgroundColor = 'hsl(' + hostHue(host) + ', 35%, 55%)';
            thumb.appendChild(el('span', null, host.charAt(0).toUpperCase()));
        }
    }

    function siteLine(url, data) {
        const site = el('div', 'lp-site');
        if (data && data.icon) {
            const icon = el('img', 'lp-icon');
            icon.alt = '';
            icon.src = data.icon;
            site.appendChild(icon);
        }
        site.appendChild(el('span', null, (data && data.siteName) || hostname(url)));
        return site;
    }

    // ---------------- hover popup -----------------------

    let popup = null;
    let hoverTimer = null;
    let activeLink = null;

    function positionPopup(link) {
        const rect = link.getClientRects()[0] || link.getBoundingClientRect();
        const gap = 6;
        const w = popup.offsetWidth;
        const h = popup.offsetHeight;
        let top = rect.bottom + gap;
        if (top + h > window.innerHeight && rect.top - gap - h > 0) {
            top = rect.top - gap - h;
        }
        const left = Math.max(8, Math.min(rect.left, window.innerWidth - w - 8));
        popup.style.top = (top + window.scrollY) + 'px';
        popup.style.left = (left + window.scrollX) + 'px';
    }

    function renderPopup(link, data, loading) {
        const url = link.href;
        popup.textContent = '';
        if (loading) {
            popup.appendChild(siteLine(url, null));
            popup.appendChild(el('div', 'lp-loading', 'loading preview…'));

        } else if (!hasPreview(data)) {
            popup.appendChild(siteLine(url, data));
            popup.appendChild(el('div', 'lp-loading', 'preview not available'));

        } else {
            if (data.image) {
                const thumb = el('div', 'lp-thumb');
                fillThumb(thumb, url, data);
                popup.appendChild(thumb);
            }
            const body = el('div', 'lp-body');
            if (data.title) {
                body.appendChild(el('div', 'lp-title', data.title));
            }
            if (data.description) {
                body.appendChild(el('div', 'lp-desc', data.description));
            }
            body.appendChild(siteLine(url, data));
            popup.appendChild(body);
        }
        popup.hidden = false;
        positionPopup(link);
    }

    function showPopup(link) {
        let loaded = false;
        getPreview(link.href, true).then(function (data) {
            loaded = true;
            if (activeLink === link) {
                renderPopup(link, data, false);
            }
        });
        // avoid the "loading" flash for cached previews
        setTimeout(function () {
            if (!loaded && activeLink === link) {
                renderPopup(link, null, true);
            }
        }, 50);
    }

    function hidePopup() {
        clearTimeout(hoverTimer);
        activeLink = null;
        if (popup) {
            popup.hidden = true;
        }
    }

    function initHoverPreviews(root) {
        if (!window.matchMedia('(hover: hover)').matches) {
            return; // touch devices - a tap opens the link directly
        }
        popup = el('div', 'link-preview-popup');
        popup.hidden = true;
        document.body.appendChild(popup);
        root.querySelectorAll('a.external').forEach(function (link) {
            if (link.closest('.link-card')) {
                return;
            }
            link.addEventListener('mouseenter', function () {
                clearTimeout(hoverTimer);
                activeLink = link;
                hoverTimer = setTimeout(function () { showPopup(link); }, HOVER_DELAY_MS);
            });
            link.addEventListener('mouseleave', hidePopup);
            link.addEventListener('click', hidePopup);
        });
        window.addEventListener('scroll', hidePopup, {passive: true});
    }

    // ---------------- link cards ------------------------

    function isSignificant(node) {
        return node.nodeType === Node.ELEMENT_NODE ||
            (node.nodeType === Node.TEXT_NODE && node.nodeValue.trim() !== '');
    }

    /**
     * If the container starts with an external link, return the link and the remaining
     * nodes (a user's note), otherwise null.
     */
    function analyzeLinkItem(container) {
        if (container.querySelector('ul, ol, table, pre, h1, h2, h3, h4, h5, h6')) {
            return null;
        }
        let nodes = Array.prototype.filter.call(container.childNodes, isSignificant);
        // "loose" markdown lists wrap the item contents in <p>
        if (nodes.length === 1 && nodes[0].tagName === 'P') {
            container = nodes[0];
            nodes = Array.prototype.filter.call(container.childNodes, isSignificant);
        }
        if (nodes.length === 0 || nodes[0].tagName !== 'A' || !nodes[0].classList.contains('external')) {
            return null;
        }
        const link = nodes[0];
        const note = Array.prototype.slice.call(
            container.childNodes, Array.prototype.indexOf.call(container.childNodes, link) + 1);
        return {link: link, note: note};
    }

    /**
     * Strip a leading separator like " - ", ": ", " | " between the link and the note
     * (modifies the DOM - call only once the item is really turned into a card)
     */
    function cleanNote(note) {
        while (note.length > 0 && note[0].nodeType === Node.TEXT_NODE) {
            const text = note[0].nodeValue.replace(/^\s*[-–—:|,]?\s*/, '');
            if (text !== '') {
                note[0].nodeValue = text;
                break;
            }
            note.shift();
        }
        return note;
    }

    function noteLength(item) {
        return item.note.reduce(function (acc, n) { return acc + n.textContent.length; }, 0);
    }

    function buildCard(tag, item, observer) {
        const url = item.link.href;
        const userText = item.link.textContent.trim();
        const userTitled = userText !== '' && userText !== url && userText.indexOf('http') !== 0;

        const card = el(tag, 'link-card');
        const main = el('a', 'lp-card-main');
        main.href = url;
        main.target = '_blank';
        main.rel = 'noopener';
        if (item.link.title) {
            main.title = item.link.title;
        }
        const thumb = el('div', 'lp-thumb');
        fillThumb(thumb, url, null);
        main.appendChild(thumb);

        const body = el('div', 'lp-body');
        const title = el('div', 'lp-title', userTitled ? userText : (userText || url));
        const desc = el('div', 'lp-desc');
        let site = siteLine(url, null);
        body.appendChild(title);
        body.appendChild(desc);
        body.appendChild(site);
        main.appendChild(body);
        card.appendChild(main);

        const noteNodes = cleanNote(item.note.slice());
        if (noteNodes.length > 0) {
            const note = el('div', 'lp-note');
            noteNodes.forEach(function (n) { note.appendChild(n); });
            card.appendChild(note);
        }

        card.riki_fill = function () {
            getPreview(url, false).then(function (data) {
                if (!data) {
                    return;
                }
                if (data.image) {
                    fillThumb(thumb, url, data);
                }
                if (data.title && !userTitled) {
                    title.textContent = data.title;
                }
                let text = data.description || '';
                if (userTitled && data.title && data.title !== userText) {
                    text = data.description ? data.title + ' – ' + data.description : data.title;
                }
                desc.textContent = text;
                const newSite = siteLine(url, data);
                body.replaceChild(newSite, site);
                site = newSite;
            });
        };
        if (observer) {
            observer.observe(card);

        } else {
            card.riki_fill();
        }
        return card;
    }

    function initLinkCards(root) {
        const observer = 'IntersectionObserver' in window ?
            new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        observer.unobserve(entry.target);
                        entry.target.riki_fill();
                    }
                });
            }, {rootMargin: '300px'}) :
            null;

        // 1) lists where each item starts with an external link
        root.querySelectorAll('ul, ol').forEach(function (list) {
            const items = Array.prototype.filter.call(list.children, function (c) { return c.tagName === 'LI'; });
            if (items.length === 0 || items.length !== list.children.length) {
                return;
            }
            const analyzed = items.map(analyzeLinkItem);
            if (analyzed.some(function (a) { return a === null; })) {
                return;
            }
            const grid = el('ul', 'link-cards');
            analyzed.forEach(function (item) {
                grid.appendChild(buildCard('li', item, observer));
            });
            list.parentNode.replaceChild(grid, list);
        });

        // 2) runs of top-level paragraphs consisting of an external link (and a short note)
        let run = null;
        Array.prototype.slice.call(root.children).forEach(function (child) {
            const item = child.tagName === 'P' ? analyzeLinkItem(child) : null;
            if (item && noteLength(item) <= MAX_PARAGRAPH_NOTE_LEN) {
                if (!run) {
                    run = el('div', 'link-cards');
                    root.insertBefore(run, child);
                }
                run.appendChild(buildCard('div', item, observer));
                child.remove();

            } else {
                run = null;
            }
        });
    }

    return {
        /**
         * @param {Element} root page content element (external links must already have the 'external' class)
         * @param {{appPath: string, linkCards: boolean}} conf
         */
        init: function (root, conf) {
            appPath = conf.appPath;
            if (conf.linkCards) {
                initLinkCards(root);
            }
            initHoverPreviews(root);
        }
    };
});
