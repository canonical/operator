# Configuration file for the Sphinx documentation builder.
#
# For a full list of options see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# NOTE: a fair bit of this is copied from:
# https://github.com/canonical/sphinx-docs-starter-pack/blob/main/conf.py


# -- Path setup --------------------------------------------------------------

import furo
import furo.navigation
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


# Furo patch to get local TOC to show in sidebar (as sphinx-rtd-theme did)
# See https://github.com/pradyunsg/furo/blob/490527b2aef00b1198770c3389a1979911ee1fcb/src/furo/__init__.py#L115-L128

_old_compute_navigation_tree = furo._compute_navigation_tree


def _compute_navigation_tree(context):
    tree_html = _old_compute_navigation_tree(context)
    if not tree_html and context.get("toc"):
        tree_html = furo.navigation.get_navigation_tree(context["toc"])
    return tree_html


furo._compute_navigation_tree = _compute_navigation_tree


# Pull in fix from https://github.com/sphinx-doc/sphinx/pull/11222/files to fix
# "invalid signature for autoattribute ('ops.pebble::ServiceDict.backoff-delay')"
import re  # noqa: E402
import sphinx.ext.autodoc  # noqa: E402
sphinx.ext.autodoc.py_ext_sig_re = re.compile(
    r'''^ ([\w.]+::)?            # explicit module name
          ([\w.]+\.)?            # module and/or class name(s)
          ([^.()]+)  \s*         # thing name
          (?: \((.*)\)           # optional: arguments
           (?:\s* -> \s* (.*))?  #           return annotation
          )? $                   # and nothing more
          ''', re.VERBOSE)


# -- Project information -----------------------------------------------------

project = 'The ops library'
copyright = '2019-2023, Canonical Ltd.'
author = 'Canonical Ltd'

html_favicon = "_static/favicon.png"

html_context = {
    "discourse": "https://discourse.charmhub.io/",
    "discourse_prefix": "https://discourse.charmhub.io/t/",
    "github_url": "https://github.com/canonical/operator",
    "github_version": "main",
    "github_folder": "/docs/",
    "github_issues": "enabled",
}

# -- General configuration ---------------------------------------------------

# If true, Sphinx will warn about all references where the target
# cannot be found.
nitpicky = True

# A list of (type, target) tuples (by default empty) that should be ignored when
# generating warnings in “nitpicky mode”. Note that type should include the
# domain name if present. Example entries would be ('py:func', 'int') or
# ('envvar', 'LD_LIBRARY_PATH').
nitpick_ignore = [
    # Please keep this list sorted alphabetically.
    ('py:class', '_ChangeDict'),
    ('py:class', '_CheckInfoDict'),
    ('py:class', '_FileInfoDict'),
    ('py:class', '_NoticeDict'),
    ('py:class', '_ProgressDict'),
    ('py:class', '_Readable'),
    ('py:class', '_RelationMetaDict'),
    ('py:class', '_ResourceMetaDict'),
    ('py:class', '_StorageMetaDict'),
    ('py:class', '_TaskDict'),
    ('py:class', '_TextOrBinaryIO'),
    ('py:class', '_WarningDict'),
    ('py:class', '_Writeable'),
    ('py:class', 'ops.charm._ContainerBaseDict'),
    ('py:class', 'ops.model._AddressDict'),
    ('py:class', 'ops.model._ConfigOption'),
    ('py:class', 'ops.model._ModelBackend'),
    ('py:class', 'ops.model._ModelCache'),
    ('py:class', 'ops.model._NetworkDict'),
    ('py:class', 'ops.pebble._FileLikeIO'),
    ('py:class', 'ops.pebble._IOSource'),
    ('py:class', 'ops.pebble._ServiceInfoDict'),
    ('py:class', 'ops.pebble._SystemInfoDict'),
    ('py:class', 'ops.pebble._WebSocket'),
    ('py:class', 'ops.storage.JujuStorage'),
    ('py:class', 'ops.storage.SQLiteStorage'),
    ('py:class', 'ops.testing.CharmType'),
    ('py:obj', 'ops.testing.CharmType'),
]

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',
    'sphinx.ext.todo',
    'sphinx.ext.viewcode',
    'sphinx_copybutton',
    'sphinx_design',
    'sphinx_tabs.tabs',

    'canonical.youtube-links',
    'canonical.related-links',
    'canonical.custom-rst-roles',
    'canonical.terminal-output',
    'notfound.extension'
]

rst_epilog = """
.. _Canonical website: https://canonical.com/
.. _reStructuredText style guide: https://canonical-documentation-with-sphinx-and-readthedocscom.readthedocs-hosted.com/style-guide/
.. _Sphinx reStructuredText Primer: https://tinyurl.com/rstprimer
.. _Canonical Documentation Style Guide: https://docs.ubuntu.com/styleguide/en
"""

source_suffix = {
    '.rst': 'restructuredtext',
}

# The document name of the “master” document, that is, the document
# that contains the root toctree directive.
master_doc = 'index'

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']


# -- Options for HTML output -------------------------------------------------

# Find the current builder
builder = "dirhtml"
if '-b' in sys.argv:
    builder = sys.argv[sys.argv.index('-b') + 1]

html_theme = 'furo'
html_last_updated_fmt = ""
html_permalinks_icon = "¶"

# -- Additional files---------------------------------------------------------
html_static_path = ['_static']
html_css_files = [
    'custom.css',
    'header.css',
    'github_issue_links.css',
    'furo_colors.css'
]

html_js_files = ['header-nav.js']
if 'github_issues' in html_context and html_context['github_issues']:
    html_js_files.append('github_issue_links.js')

# -- Options for sphinx.ext.todo ---------------------------------------------

#  If this is True, todo and todolist produce output, else they
#  produce nothing. The default is False.
todo_include_todos = False


# -- Options for sphinx.ext.autodoc ------------------------------------------

# This value controls how to represents typehints. The setting takes the
# following values:
#     'signature' – Show typehints as its signature (default)
#     'description' – Show typehints as content of function or method
#     'none' – Do not show typehints
autodoc_typehints = 'signature'

# This value selects what content will be inserted into the main body of an
# autoclass directive. The possible values are:
#     'class' - Only the class’ docstring is inserted. This is the
#               default. You can still document __init__ as a separate method
#               using automethod or the members option to autoclass.
#     'both' - Both the class’ and the __init__ method’s docstring are
#              concatenated and inserted.
#     'init' - Only the __init__ method’s docstring is inserted.
autoclass_content = 'class'

# This value selects if automatically documented members are sorted
# alphabetical (value 'alphabetical'), by member type (value
# 'groupwise') or by source order (value 'bysource'). The default is
# alphabetical.
autodoc_member_order = 'alphabetical'

autodoc_default_options = {
    'members': None,            # None here means "yes"
    'undoc-members': None,
    'show-inheritance': None,
}


# -- Options for sphinx.ext.intersphinx --------------------------------------

# This config value contains the locations and names of other projects
# that should be linked to in this documentation.
intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}
