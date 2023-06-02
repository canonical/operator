# Configuration file for the Sphinx documentation builder.
#
# For a full list of options see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html


# -- Path setup --------------------------------------------------------------

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# Pull in fix from https://github.com/sphinx-doc/sphinx/pull/11222/files to fix
# "invalid signature for autoattribute ('ops.pebble::ServiceDict.backoff-delay')"
import re
import sphinx.ext.autodoc
sphinx.ext.autodoc.py_ext_sig_re = re.compile(
    r'''^ ([\w.]+::)?            # explicit module name
          ([\w.]+\.)?            # module and/or class name(s)
          ([^.()]+)  \s*         # thing name
          (?: \((.*)\)           # optional: arguments
           (?:\s* -> \s* (.*))?  #           return annotation
          )? $                   # and nothing more
          ''', re.VERBOSE)


# -- Project information -----------------------------------------------------

project = 'The Operator Framework'
copyright = '2019-2023, Canonical Ltd.'
author = 'Canonical Ltd'


# -- General configuration ---------------------------------------------------

# If true, Sphinx will warn about all references where the target
# cannot be found.
nitpicky = True

# A list of (type, target) tuples (by default empty) that should be ignored when
# generating warnings in “nitpicky mode”. Note that type should include the
# domain name if present. Example entries would be ('py:func', 'int') or
# ('envvar', 'LD_LIBRARY_PATH').
nitpick_ignore = [
    ('py:class', 'ops.model._ModelBackend'),
    ('py:class', 'ops.model._ModelCache'),
    ('py:class', '_AddressDict'),
    ('py:class', '_NetworkDict'),
    ('py:class', '_RelationMetaDict'),
    ('py:class', '_ResourceMetaDict'),
    ('py:class', '_StorageMetaDict'),
    ('py:class', '_ChangeData'),
    ('py:class', '_ChangeDict'),
    ('py:class', '_InfoDict'),
    ('py:class', '_IOSource'),
    ('py:class', '_TextOrBinaryIO'),
    ('py:class', '_Readable'),
    ('py:class', '_Writeable'),
    ('py:class', '_WebSocket'),
    ('py:class', '_FileInfoDict'),
    ('py:class', '_PlanDict'),
    ('py:class', '_ServiceInfoDict'),
    ('py:class', '_SystemInfoDict'),
    ('py:class', '_TaskData'),
    ('py:class', '_TaskDict'),
    ('py:class', '_ProgressDict'),
    ('py:class', '_WarningDict'),
    ('py:class', 'ops.storage.SQLiteStorage'),
    ('py:class', 'ops.storage.JujuStorage'),
    ('py:class', 'ops.testing.CharmType'),
    ('py:obj', 'ops.testing.CharmType'),
]

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.todo',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
]

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

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_rtd_theme'  # 'alabaster'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = []


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
