# Configuration file for the Sphinx documentation builder.
#
# For a full list of options see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html


# -- Path setup --------------------------------------------------------------

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# -- Project information -----------------------------------------------------

project = 'The Operator Framework'
copyright = '2019-2020, Canonical Ltd.'
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
    ('py:class', 'TextIO'),  # typing.TextIO confuses the nitpicker
    ('py:class', 'method'),  # types.Method confuses the nitpicker
    ('py:class', '_ModelBackend'),  # private
    ('py:class', '_ModelCache'), # private
    ('py:class', 'ipaddress.ip_address'), # fake (AFAIK there is no ABC)
    ('py:class', 'ipaddress.ip_network'), # ditto
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
html_static_path = ['_static']


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
autodoc_typehints = 'description'

# This value selects what content will be inserted into the main body of an
# autoclass directive. The possible values are:
#     'class' - Only the class’ docstring is inserted. This is the
#               default. You can still document __init__ as a separate method
#               using automethod or the members option to autoclass.
#     'both' - Both the class’ and the __init__ method’s docstring are
#              concatenated and inserted.
#     'init' - Only the __init__ method’s docstring is inserted.
autoclass_content = 'both'

# This value selects if automatically documented members are sorted
# alphabetical (value 'alphabetical'), by member type (value
# 'groupwise') or by source order (value 'bysource'). The default is
# alphabetical.
autodoc_member_order = 'bysource'

autodoc_default_options = {
    'members': None,            # None here means "yes"
    'undoc-members': None,
    'show-inheritance': None,
}


# -- Options for sphinx.ext.intersphinx --------------------------------------

# This config value contains the locations and names of other projects
# that should be linked to in this documentation.
intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}
