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

## Tips

### Transforming a directory into a picture gallery

Into a respective directory, put the following JSON file:

```json
{"directoryType": "gallery"}
```

### Directory index

There is no need to include `index.md` into each directory. In case Riki does not found one,
it automatically displays a list of containing files.


## Requirements


* Python 3.6+
* an HTTP proxy server

