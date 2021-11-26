Riki
====

Riki is an application intended to users who write their texts/knowledge bases/etc. in a form
of Markdown files stored in a filesystem directory structure. The name stands for *read only
 wiki* which may sound strange but the truth is that Riki just presents your data via web.

It expects you to edit your files using a common pure-text editor (vim, writemonkey, notepad++ etc.) 
and organize them using directories.

Recommended workflow
--------------------

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
changegroup.fulltext = /var/www/riki/index.py /var/www/riki/data -n
```

Requirements
------------

* Python 3.6+
    - [markdown for Python](https://pypi.python.org/pypi/Markdown)
    - [Jinja](http://jinja.pocoo.org/)
    - [web.py](http://webpy.org/)   
   
