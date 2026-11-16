# Riki

Riki is a Wiki-ish application intended to users who write their texts/knowledge bases/etc. in a form
of Markdown files stored in a local filesystem directory structure. The name stands for *read only
 wiki* which may sound strange but the truth is that Riki just presents your data via web.

## Recommended workflow

While it is perfectly OK to move and copy your files around, this may soon lead to
chaos. The best way to work with riki is to create a Mercurial or Git repository
in your Riki data directory and upload your files by pushing them via one of the versioning
systems. It will allow you to keep track of changes and also to automatize some data deployment tasks.

In Mercurial you can define a series of actions ('hooks') which trigger whenever you
push your changes. Following configuration ensures that your data are updated and indexed once
you push from your local repository.

```
[hooks]
changegroup =
changegroup.update_data = hg update
changegroup.fulltext = /var/www/riki/search.py --data-dir /var/opt/riki/data -x /var/opt/riki/srch-index
```

## Editing pages via web

Riki can optionally edit pages directly in a browser (raw Markdown). Each save is committed
to the Mercurial repository in the data directory and the page is re-indexed in the fulltext index.
New pages can be created by opening a non-existing page and clicking "create this page".

**Riki has no authentication** - enable editing only if the access is restricted otherwise
(e.g. by a proxy server or a local network). In the configuration:

```json
{
  "enableEditing": true,
  "hgCommitUser": "Riki <riki@localhost>"
}
```

If `hgCommitUser` is not set, Mercurial's own configuration (`ui.username`) is used. The process
running Riki must have write access to the data directory (including `.hg`) and to the search index.
Commits made via the web stay in the server repository - don't forget to `hg pull` them into your
local clones.

Note: the fulltext index requires a full rebuild (`search.py` without `-f`) once after upgrading
to this version. A single file can be re-indexed via `search.py -f path/to/file.md`.

## Tips

### Transforming a directory into a picture gallery

Into a respective directory, put the following JSON file:

```json
{"directoryType": "gallery"}
```

### Previews of external links

With `linkPreviewCacheDir` set in the configuration, hovering an external link shows a popup
with the target page's title, description and image (taken from its OpenGraph/meta tags).
Riki fetches each link once and caches the result (30 days; failures for 1 day) including
downscaled images, so browsers load everything from Riki itself.

```json
{
  "linkPreviewCacheDir": "/var/opt/riki/link-preview-cache"
}
```

By default, links pointing to loopback/private network addresses (e.g. a NAS or a router in
your LAN) are not previewed, as the preview service could otherwise be used to probe your local
network by anyone with access to Riki. If Riki is accessible only from your network,
you can enable them via `"linkPreviewAllowPrivate": true`.

### Link cards

Pages consisting mostly of links can render them as a grid of cards (image, title, description,
your note). Either put the following line anywhere into a page:

```
<!-- riki:link-cards -->
```

or turn the mode on for a whole directory in its `metadata.json`:

```json
{"linkCards": true}
```

Converted are lists where *every* item starts with an external link (text after the link
becomes the card's note, a leading separator like ` - ` or `: ` is removed) and top-level
paragraphs containing just an external link (plus an optional short note). Other lists and
links in a running text stay untouched. Link cards require `linkPreviewCacheDir` to be set.

### Directory index

There is no need to include `index.md` into each directory. In case Riki does not found one,
it automatically displays a list of containing files.


## Requirements


* Python 3.6+
* an HTTP proxy server

