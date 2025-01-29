# Copyright 2019 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import os
import pathlib
import sys

from docutils import nodes

import inspect
import sphinx.ext.autodoc
from sphinx import addnodes
from sphinx.util.docutils import SphinxDirective


sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

# Pull in fix from https://github.com/sphinx-doc/sphinx/pull/11222/files to fix
# "invalid signature for autoattribute ('ops.pebble::ServiceDict.backoff-delay')"
import re

sphinx.ext.autodoc.py_ext_sig_re = re.compile(
    r"""^ ([\w.]+::)?            # explicit module name
          ([\w.]+\.)?            # module and/or class name(s)
          ([^.()]+)  \s*         # thing name
          (?: \[\s*(.*)\s*])?    # optional: type parameters list, Sphinx 7&8
          (?: \((.*)\)           # optional: arguments
           (?:\s* -> \s* (.*))?  #           return annotation
          )? $                   # and nothing more
          """,
    re.VERBOSE,
)

# Custom configuration for the Sphinx documentation builder.
# All configuration specific to your project should be done in this file.
#
# The file is included in the common conf.py configuration file.
# You can modify any of the settings below or add any configuration that
# is not covered by the common conf.py file.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
#
# If you're not familiar with Sphinx and don't want to use advanced
# features, it is sufficient to update the settings in the "Project
# information" section.

############################################################
### Project information
############################################################

# Product name
project = 'The ops library'
author = 'Canonical Ltd.'

# The title you want to display for the documentation in the sidebar.
# You might want to include a version number here.
# To not display any title, set this option to an empty string.
html_title = project + ' documentation'

# The default value uses the current year as the copyright year.
#
# For static works, it is common to provide the year of first publication.
# Another option is to give the first year and the current year
# for documentation that is often changed, e.g. 2022–2023 (note the en-dash).
#
# A way to check a GitHub repo's creation date is to obtain a classic GitHub
# token with 'repo' permissions here: https://github.com/settings/tokens
# Next, use 'curl' and 'jq' to extract the date from the GitHub API's output:
#
# curl -H 'Authorization: token <TOKEN>' \
#   -H 'Accept: application/vnd.github.v3.raw' \
#   https://api.github.com/repos/canonical/<REPO> | jq '.created_at'

copyright = '%s, %s' % (datetime.date.today().year, author)  # noqa: A001

## Open Graph configuration - defines what is displayed as a link preview
## when linking to the documentation from another website (see https://ogp.me/)
# The URL where the documentation will be hosted (leave empty if you
# don't know yet)
# NOTE: If no ogp_* variable is defined (e.g. if you remove this section) the
# sphinxext.opengraph extension will be disabled.
ogp_site_url = 'https://ops.readthedocs.io/en/latest/'
# The documentation website name (usually the same as the product name)
ogp_site_name = project
# The URL of an image or logo that is used in the preview
ogp_image = 'https://assets.ubuntu.com/v1/253da317-image-document-ubuntudocs.svg'

# Update with the local path to the favicon for your product
# (default is the circle of friends)
html_favicon = '.sphinx/_static/favicon.png'

# (Some settings must be part of the html_context dictionary, while others
#  are on root level. Don't move the settings.)
html_context = {
    # Change to the link to the website of your product (without "https://")
    # For example: "ubuntu.com/lxd" or "microcloud.is"
    # If there is no product website, edit the header template to remove the
    # link (see the readme for instructions).
    'product_page': 'juju.is/docs/sdk',
    # Add your product tag (the orange part of your logo, will be used in the
    # header) to ".sphinx/_static" and change the path here (start with "_static")
    # (default is the circle of friends)
    'product_tag': '_static/tag.png',
    # Change to the discourse instance you want to be able to link to
    # using the :discourse: metadata at the top of a file
    # (use an empty value if you don't want to link)
    'discourse': 'https://discourse.charmhub.io/',
    # Change to the Mattermost channel you want to link to
    # (use an empty value if you don't want to link)
    'mattermost': '',
    # Change to the Matrix channel you want to link to
    # (use an empty value if you don't want to link)
    'matrix': 'https://matrix.to/#/#charmhub-charmdev:ubuntu.com',
    # Change to the GitHub URL for your project
    'github_url': 'https://github.com/canonical/operator',
    # Change to the branch for this version of the documentation
    'github_version': 'main',
    # Change to the folder that contains the documentation
    # (usually "/" or "/docs/")
    'github_folder': '/docs/',
    # Change to an empty value if your GitHub repo doesn't have issues enabled.
    # This will disable the feedback button and the issue link in the footer.
    'github_issues': 'enabled',
    # Controls the existence of Previous / Next buttons at the bottom of pages
    # Valid options: none, prev, next, both
    'sequential_nav': 'none',
}
# Addons-by-default, see: https://about.readthedocs.com/blog/2024/07/addons-by-default/
if os.environ.get('READTHEDOCS', '') == 'True':
    html_context['READTHEDOCS'] = True
    # The following are needed, see: https://github.com/pradyunsg/furo/blob/main/docs/conf.py#L135.
    html_context['current_version'] = 'latest'
    html_context['conf_py_path'] = '/docs/'
    html_context['display_github'] = True
    html_context['github_user'] = 'canonical'
    html_context['github_repo'] = 'operator'
    html_context['github_version'] = 'main'
    html_context['slug'] = 'operator'

# If your project is on documentation.ubuntu.com, specify the project
# slug (for example, "lxd") here.
slug = ''

############################################################
### Redirects
############################################################

# Set up redirects (https://documatt.gitlab.io/sphinx-reredirects/usage.html)
# For example: 'explanation/old-name.html': '../how-to/prettify.html',
# You can also configure redirects in the Read the Docs project dashboard
# (see https://docs.readthedocs.io/en/stable/guides/redirects.html).
# NOTE: If this variable is not defined, set to None, or the dictionary is empty,
# the sphinx_reredirects extension will be disabled.
redirects = {}

############################################################
### Link checker exceptions
############################################################

# Links to ignore when checking links
linkcheck_ignore = ['http://127.0.0.1:8000']

# Pages on which to ignore anchors
# (This list will be appended to linkcheck_anchors_ignore_for_url)
custom_linkcheck_anchors_ignore_for_url = []

############################################################
### Additions to default configuration
############################################################

## The following settings are appended to the default configuration.
## Use them to extend the default functionality.
# NOTE: Remove this variable to disable the MyST parser extensions.
custom_myst_extensions = []

# Add custom Sphinx extensions as needed.
# This array contains recommended extensions that should be used.
# NOTE: The following extensions are handled automatically and do
# not need to be added here: myst_parser, sphinx_copybutton, sphinx_design,
# sphinx_reredirects, sphinxcontrib.jquery, sphinxext.opengraph
custom_extensions = [
    'sphinx_tabs.tabs',
    'canonical.youtube-links',
    'canonical.related-links',
    'canonical.custom-rst-roles',
    'canonical.terminal-output',
    'notfound.extension',
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',
    'sphinx.ext.todo',
    'sphinx.ext.viewcode',
]

# Add custom required Python modules that must be added to the
# .sphinx/requirements.txt file.
# NOTE: The following modules are handled automatically and do not need to be
# added here: canonical-sphinx-extensions, furo, linkify-it-py, myst-parser,
# pyspelling, sphinx, sphinx-autobuild, sphinx-copybutton, sphinx-design,
# sphinx-notfound-page, sphinx-reredirects, sphinx-tabs, sphinxcontrib-jquery,
# sphinxext-opengraph
custom_required_modules = []

# Add files or directories that should be excluded from processing.
custom_excludes = [
    'doc-cheat-sheet*',
]

# Add CSS files (located in .sphinx/_static/)
custom_html_css_files = []

# Add JavaScript files (located in .sphinx/_static/)
custom_html_js_files = []

## The following settings override the default configuration.

# Specify a reST string that is included at the end of each file.
# If commented out, use the default (which pulls the reuse/links.txt
# file into each reST file).
custom_rst_epilog = ''

# By default, the documentation includes a feedback button at the top.
# You can disable it by setting the following configuration to True.
disable_feedback_button = False

# Add tags that you want to use for conditional inclusion of text
# (https://www.sphinx-doc.org/en/master/usage/restructuredtext/directives.html#tags)
custom_tags = []

############################################################
### Additional configuration
############################################################

## Add any configuration that is not covered by the common conf.py file.

# Define a :center: role that can be used to center the content of table cells.
rst_prolog = """
.. role:: center
   :class: align-center
"""


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
    'members': None,  # None here means "yes"
    'undoc-members': None,
    'show-inheritance': None,
}

# -- Options for sphinx.ext.intersphinx --------------------------------------

# This config value contains the locations and names of other projects
# that should be linked to in this documentation.
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'juju': ('https://canonical-juju.readthedocs-hosted.com/en/latest/', None),
    'charmcraft': ('https://canonical-charmcraft.readthedocs-hosted.com/en/stable/', None),
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
    ('py:class', '_EntityStatus'),
    ('py:class', '_Event'),
    ('py:class', '_FileInfoDict'),
    ('py:class', '_NoticeDict'),
    ('py:class', '_ProgressDict'),
    ('py:class', '_RawPortProtocolLiteral'),
    ('py:class', '_Readable'),
    ('py:class', '_RelationMetaDict'),
    ('py:class', '_ResourceMetaDict'),
    ('py:class', '_StorageMetaDict'),
    ('py:class', '_TaskDict'),
    ('py:class', '_TextOrBinaryIO'),
    ('py:class', '_WarningDict'),
    ('py:class', '_Writeable'),
    ('py:class', 'AnyJson'),
    ('py:class', 'CharmType'),
    ('py:obj', 'ops._private.harness.CharmType'),
    ('py:class', 'ops._private.harness.CharmType'),
    ('py:class', 'ops.charm._ContainerBaseDict'),
    ('py:class', 'ops.model._AddressDict'),
    ('py:class', 'ops.model._GenericLazyMapping'),
    ('py:class', 'ops.model._ModelBackend'),
    ('py:class', 'ops.model._ModelCache'),
    ('py:class', 'ops.model._NetworkDict'),
    ('py:class', 'ops.model._SupportsKeysAndGetItem'),
    ('py:class', 'ops.pebble._FileLikeIO'),
    ('py:class', 'ops.pebble._IOSource'),
    ('py:class', 'ops.pebble._ServiceInfoDict'),
    ('py:class', 'ops.pebble._SystemInfoDict'),
    ('py:class', 'ops.pebble._WebSocket'),
    ('py:class', 'ops.storage.JujuStorage'),
    ('py:class', 'ops.storage.SQLiteStorage'),
    ('py:class', 'ops.testing._ConfigOption'),
    ('py:class', 'ops.testing.CharmType'),
    ('py:obj', 'ops.testing.CharmType'),
    ('py:obj', 'scenario.state.CharmType'),
    ('py:class', 'scenario.state.CharmType'),
    ('py:class', 'scenario.state._EntityStatus'),
    ('py:class', 'scenario.state._Event'),
    ('py:class', 'scenario.state._max_posargs.<locals>._MaxPositionalArgs'),
]


# Monkeypatch Sphinx to look for __init__ rather than __new__ for the subclasses
# of _MaxPositionalArgs.
_real_get_signature = sphinx.ext.autodoc.ClassDocumenter._get_signature


def _custom_get_signature(self):
    if any(p.__name__ == '_MaxPositionalArgs' for p in self.object.__mro__):
        signature = inspect.signature(self.object)
        parameters = []
        for position, param in enumerate(signature.parameters.values()):
            if position >= self.object._max_positional_args:
                parameters.append(param.replace(kind=inspect.Parameter.KEYWORD_ONLY))
            else:
                parameters.append(param)
        signature = signature.replace(parameters=parameters)
        return None, None, signature
    return _real_get_signature(self)


sphinx.ext.autodoc.ClassDocumenter._get_signature = _custom_get_signature


# This is very strongly based on
# https://github.com/sphinx-doc/sphinx/blob/03b9134ee00e98df4f8b5f6d22f345cdafe31870/sphinx/domains/changeset.py#L46
# Unfortunately, the built-in class is not easily subclassable without also
# requiring extra CSS.
class JujuVersion(SphinxDirective):
    """Directive to describe in which version of Juju a feature was added or removed."""

    change = 'changed'

    has_content = True
    required_arguments = 1
    optional_arguments = 1
    final_argument_whitespace = True
    option_spec = {}

    def run(self):
        node = addnodes.versionmodified()
        node.document = self.state.document
        self.set_source_info(node)
        # Make the <div> have a class matching the built-in directives so that
        # we don't need custom CSS.
        node['type'] = f'version{self.change}'
        node['version'] = self.arguments[0]
        text = f'{self.text} in Juju version {self.arguments[0]}'
        if len(self.arguments) == 2:
            inodes, messages = self.state.inline_text(self.arguments[1], self.lineno + 1)
            para = nodes.paragraph(self.arguments[1], '', *inodes, translatable=False)
            self.set_source_info(para)
            node.append(para)
        else:
            messages = []
        if self.content:
            node += self.parse_content_to_nodes()
        classes = ['versionmodified', self.change]
        if len(node) > 0 and isinstance(node[0], nodes.paragraph):
            # The contents start with a paragraph.
            if node[0].rawsource:
                # Make the first paragraph translatable.
                content = nodes.inline(node[0].rawsource, translatable=True)
                content.source = node[0].source
                content.line = node[0].line
                content += node[0].children
                node[0].replace_self(nodes.paragraph('', '', content, translatable=False))

            para = node[0]
            para.insert(0, nodes.inline('', '%s: ' % text, classes=classes))
        elif len(node) > 0:
            # The contents do not start with a paragraph.
            para = nodes.paragraph(
                '', '', nodes.inline('', '%s: ' % text, classes=classes), translatable=False
            )
            node.insert(0, para)
        else:
            # The contents are empty.
            para = nodes.paragraph(
                '', '', nodes.inline('', '%s.' % text, classes=classes), translatable=False
            )
            node.append(para)

        domain = self.env.get_domain('changeset')
        domain.note_changeset(node)

        ret = [node]
        ret += messages
        return ret


class JujuAdded(JujuVersion):
    change = 'added'
    text = 'Added'


class JujuChanged(JujuVersion):
    change = 'changed'
    text = 'Changed'


class JujuRemoved(JujuVersion):
    change = 'removed'
    text = 'Scheduled for removal'


def setup(app):
    app.add_directive('jujuadded', JujuAdded)
    app.add_directive('jujuchanged', JujuChanged)
    app.add_directive('jujuremoved', JujuRemoved)
