import datetime
import importlib
import os
import pathlib
import sys
import yaml

from docutils import nodes

import inspect
import re
import sphinx.ext.autodoc
from sphinx import addnodes
from sphinx.util.docutils import SphinxDirective


# Check that the ops package is installed in the Sphinx venv.
if importlib.util.find_spec("ops") is None:
    print(
        "Error: The ops package is not available. "
        "Check whether the $(VENVDIR) target in our Makefile has been changed or reverted."
    )
    sys.exit(1)

# Make sure that sphinx.ext.autodoc can find our Python source files.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

# Configuration for the Sphinx documentation builder.
# All configuration specific to your project should be done in this file.
#
# If you're new to Sphinx and don't want any advanced or custom features,
# just go through the items marked 'TODO'.
#
# A complete list of built-in Sphinx configuration values:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
#
# Our starter pack uses the custom Canonical Sphinx extension
# to keep all documentation based on it consistent and on brand:
# https://github.com/canonical/canonical-sphinx


#######################
# Project information #
#######################

# Project name
#
# TODO: Update with the official name of your project or product

project = "Ops"
author = "Canonical Ltd."


# Sidebar documentation title; best kept reasonably short
#
# TODO: To include a version number, add it here (hardcoded or automated).
#
# TODO: To disable the title, set to an empty string.

html_title = project + " documentation"


# Copyright string; shown at the bottom of the page
#
# Now, the starter pack uses CC-BY-SA as the license
# and the current year as the copyright year.
#
# TODO: If your docs need another license, specify it instead of 'CC-BY-SA'.
#
# TODO: If your documentation is a part of the code repository of your project,
#       it inherits the code license instead; specify it instead of 'CC-BY-SA'.
#
# NOTE: For static works, it is common to provide the first publication year.
#       Another option is to provide both the first year of publication
#       and the current year, especially for docs that frequently change,
#       e.g. 2022–2023 (note the en-dash).
#
#       A way to check a repo's creation date is to get a classic GitHub token
#       with 'repo' permissions; see https://github.com/settings/tokens
#       Next, use 'curl' and 'jq' to extract the date from the API's output:
#
#       curl -H 'Authorization: token <TOKEN>' \
#         -H 'Accept: application/vnd.github.v3.raw' \
#         https://api.github.com/repos/canonical/<REPO> | jq '.created_at'

copyright = "%s, %s" % (datetime.date.today().year, author)


# Documentation website URL
#
# TODO: Update with the official URL of your docs or leave empty if unsure.
#
# NOTE: The Open Graph Protocol (OGP) enhances page display in a social graph
#       and is used by social media platforms; see https://ogp.me/

ogp_site_url = "https://documentation.ubuntu.com/ops/latest/"


# Preview name of the documentation website
#
# TODO: To use a different name for the project in previews, update as needed.

ogp_site_name = project


# Preview image URL
#
# TODO: To customise the preview image, update as needed.

ogp_image = "https://assets.ubuntu.com/v1/cc828679-docs_illustration.svg"


# Product favicon; shown in bookmarks, browser tabs, etc.

# TODO: To customise the favicon, uncomment and update as needed.

# html_favicon = '.sphinx/_static/favicon.png'


# Dictionary of values to pass into the Sphinx context for all pages:
# https://www.sphinx-doc.org/en/master/usage/configuration.html#confval-html_context

html_context = {
    # Product page URL; can be different from product docs URL
    #
    # TODO: Change to your product website URL,
    #       dropping the 'https://' prefix, e.g. 'ubuntu.com/lxd'.
    #
    # TODO: If there's no such website,
    #       remove the {{ product_page }} link from the page header template
    #       (usually .sphinx/_templates/header.html; also, see README.rst).
    "product_page": "juju.is",
    # Product tag image; the orange part of your logo, shown in the page header
    #
    # TODO: To add a tag image, uncomment and update as needed.
    'product_tag': '_static/logos/juju-logo-no-text.png',
    # Your Discourse instance URL
    #
    # TODO: Change to your Discourse instance URL or leave empty.
    #
    # NOTE: If set, adding ':discourse: 123' to an .rst file
    #       will add a link to Discourse topic 123 at the bottom of the page.
    "discourse": "https://discourse.charmhub.io/",
    # Your Mattermost channel URL
    #
    # TODO: Change to your Mattermost channel URL or leave empty.
    "mattermost": "",
    # Your Matrix channel URL
    #
    # TODO: Change to your Matrix channel URL or leave empty.
    "matrix": "https://matrix.to/#/#charmhub-charmdev:ubuntu.com",
    # Your documentation GitHub repository URL
    #
    # TODO: Change to your documentation GitHub repository URL or leave empty.
    #
    # NOTE: If set, links for viewing the documentation source files
    #       and creating GitHub issues are added at the bottom of each page.
    "github_url": "https://github.com/canonical/operator",
    # Docs branch in the repo; used in links for viewing the source files
    #
    # TODO: To customise the branch, uncomment and update as needed.
    'repo_default_branch': 'main',
    # Docs location in the repo; used in links for viewing the source files
    #


    # TODO: To customise the directory, uncomment and update as needed.
    "repo_folder": "/docs/",
    # TODO: To enable or disable the Previous / Next buttons at the bottom of pages
    # Valid options: none, prev, next, both
    # "sequential_nav": "both",
    # TODO: To enable listing contributors on individual pages, set to True
    "display_contributors": False,

    # Required for feedback button
    'github_issues': 'enabled',
}

# TODO: To enable the edit button on pages, uncomment and change the link to a
# public repository on GitHub or Launchpad. Any of the following link domains
# are accepted:
# - https://github.com/example-org/example"
# - https://launchpad.net/example
# - https://git.launchpad.net/example
#
# html_theme_options = {
# 'source_edit_link': 'https://github.com/canonical/sphinx-docs-starter-pack',
# }

# Project slug; see https://meta.discourse.org/t/what-is-category-slug/87897
#
# TODO: If your documentation is hosted on https://docs.ubuntu.com/,
#       uncomment and update as needed.

slug = 'ops'

#######################
# Sitemap configuration: https://sphinx-sitemap.readthedocs.io/
#######################

# Use RTD canonical URL to ensure duplicate pages have a specific canonical URL

html_baseurl = os.environ.get("READTHEDOCS_CANONICAL_URL", "/")

# sphinx-sitemap uses html_baseurl to generate the full URL for each page:

sitemap_url_scheme = '{link}'

# Include `lastmod` dates in the sitemap:

sitemap_show_lastmod = True

# Exclude generated pages from the sitemap:

sitemap_excludes = [
    '404/',
    'genindex/',
    'py-modindex/',
    '_modules/*',
    'search/',
]

#######################
# Template and asset locations
#######################

html_static_path = ["_static"]
templates_path = ["_templates"]


#############
# Redirects #
#############

# To set up redirects: https://documatt.gitlab.io/sphinx-reredirects/usage.html
# For example: 'explanation/old-name.html': '../how-to/prettify.html',

# To set up redirects in the Read the Docs project dashboard:
# https://docs.readthedocs.io/en/stable/guides/redirects.html

# NOTE: If undefined, set to None, or empty,
#       the sphinx_reredirects extension will be disabled.

redirects = {}


###########################
# Link checker exceptions #
###########################

# During linkcheck, if a target URL matches any of these regexes (using re.match)
# then the URL is skipped.

linkcheck_ignore = [
    # Excluded because the pages don't contain elements with an ID matching the URL fragment.
    r"https://matrix\.to/#/",
    r"https://documentation\.ubuntu\.com/pebble/reference/api/#/",
    r"https://documentation\.ubuntu\.com/juju/3\.6/reference/hook-command/list-of-hook-commands/#list-of-hook-commands",
]


# A regex list of URLs where anchors are ignored by 'make linkcheck'

linkcheck_anchors_ignore_for_url = [r"https://github\.com/.*"]

# give linkcheck multiple tries on failure
# linkcheck_timeout = 30
linkcheck_retries = 3

########################
# Configuration extras #
########################

# Custom MyST syntax extensions; see
# https://myst-parser.readthedocs.io/en/latest/syntax/optional.html
#
# NOTE: By default, the following MyST extensions are enabled:
#       substitution, deflist, linkify

# myst_enable_extensions = set()


# Custom Sphinx extensions; see
# https://www.sphinx-doc.org/en/master/usage/extensions/index.html

# NOTE: The canonical_sphinx extension is required for the starter pack.
#       It automatically enables the following extensions:
#       - custom-rst-roles
#       - myst_parser
#       - notfound.extension
#       - related-links
#       - sphinx_copybutton
#       - sphinx_design
#       - sphinx_reredirects
#       - sphinx_tabs.tabs
#       - sphinxcontrib.jquery
#       - sphinxext.opengraph
#       - terminal-output
#       - youtube-links

extensions = [
    "canonical_sphinx",
    "notfound.extension",
    "sphinx_design",
    "sphinx_reredirects",
    "sphinx_tabs.tabs",
    "sphinxcontrib.jquery",
    "sphinxext.opengraph",
    "sphinx_config_options",
    "sphinx_contributor_listing",
    "sphinx_filtered_toctree",
    "sphinx_related_links",
    "sphinx_roles",
    "sphinx_terminal",
    "sphinx_ubuntu_images",
    "sphinx_youtube_links",
    "sphinxcontrib.cairosvgconverter",
    "sphinx_last_updated_by_git",
    "sphinx.ext.intersphinx",
    "sphinx_sitemap",
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.todo',
    'sphinx.ext.viewcode',
]

# Excludes files or directories from processing

exclude_patterns = []

# Adds custom CSS files, located under 'html_static_path'

html_css_files = [
    "cookie-banner.css",
    "project_specific.css",
]


# Adds custom JavaScript files, located under 'html_static_path'

html_js_files = [
    "analytics-bundle.js",
]


# Specifies a reST snippet to be appended to each .rst file

# rst_epilog = """
# .. include:: /reuse/links.txt
# .. include:: /reuse/substitutions.txt
# """

# Feedback button at the top; enabled by default
#
# TODO: To disable the button, uncomment this.

# disable_feedback_button = True


# Your manpage URL
#
# TODO: To enable manpage links, uncomment and replace {codename} with required
#       release, preferably an LTS release (e.g. noble). Do *not* substitute
#       {section} or {page}; these will be replaced by sphinx at build time
#
# NOTE: If set, adding ':manpage:' to an .rst file
#       adds a link to the corresponding man section at the bottom of the page.

# manpages_url = 'https://manpages.ubuntu.com/manpages/{codename}/en/' + \
#     'man{section}/{page}.{section}.html'


# Specifies a reST snippet to be prepended to each .rst file
# This defines a :center: role that centers table cell content.
# This defines a :h2: role that styles content for use with PDF generation.

rst_prolog = """
.. role:: center
   :class: align-center
.. role:: h2
    :class: hclass2
.. role:: woke-ignore
    :class: woke-ignore
.. role:: vale-ignore
    :class: vale-ignore
"""

# Workaround for https://github.com/canonical/canonical-sphinx/issues/34

if "discourse_prefix" not in html_context and "discourse" in html_context:
    html_context["discourse_prefix"] = html_context["discourse"] + "/t/"

# Workaround for substitutions.yaml

if os.path.exists('./reuse/substitutions.yaml'):
    with open('./reuse/substitutions.yaml', 'r') as fd:
        myst_substitutions = yaml.safe_load(fd.read())

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

# This value stacks args vertically if a signature is too long.
maximum_signature_line_length = 80

# -- Options for sphinx.ext.intersphinx --------------------------------------

# This config value contains the locations and names of other projects
# that should be linked to in this documentation.
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'jubilant': ('https://documentation.ubuntu.com/jubilant', None),
    'juju': ('https://documentation.ubuntu.com/juju/3.6', None),
    'charmcraft': ('https://documentation.ubuntu.com/charmcraft/latest', None),
    'charmlibs': ('https://documentation.ubuntu.com/charmlibs/', None),
    'multipass': ('https://documentation.ubuntu.com/multipass/latest', None),
    'pebble': ('https://documentation.ubuntu.com/pebble', None),
    'otel': ('https://opentelemetry-python.readthedocs.io/en/latest/', None),
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
    ('py:class', '_AddressDict'),
    ('py:class', '_ChangeDict'),
    ('py:class', '_CheckInfoDict'),
    ('py:class', '_EntityStatus'),
    ('py:class', '_Event'),
    ('py:class', '_FileInfoDict'),
    ('py:class', '_NetworkDict'),
    ('py:class', '_NoticeDict'),
    ('py:class', '_ProgressDict'),
    ('py:class', '_RawPortProtocolLiteral'),
    ('py:class', '_RelationMetaDict'),
    ('py:class', '_ResourceMetaDict'),
    ('py:class', '_StateKwargs'),
    ('py:class', '_StorageMetaDict'),
    ('py:class', '_TaskDict'),
    ('py:class', '_TextOrBinaryIO'),
    ('py:class', '_WarningDict'),
    ('py:class', 'AnyJson'),
    ('py:class', 'BasicIdentityDict'),
    ('py:class', 'CharmType'),
    ('py:class', 'LocalIdentityDict'),
    ('py:class', 'IdentityDict'),
    ('py:class', 'ReadableSpan'),
    ('py:obj', 'ops._private.harness.CharmType'),
    ('py:class', 'ops._private.harness.CharmType'),
    ('py:class', 'ops.charm._ContainerBaseDict'),
    ('py:class', 'ops.charm._T'),
    ('py:class', 'ops.model._AddressDict'),
    ('py:class', 'ops.model._GenericLazyMapping'),
    ('py:class', 'ops.model._ModelBackend'),
    ('py:class', 'ops.model._ModelCache'),
    ('py:class', 'ops.model._NetworkDict'),
    ('py:class', 'ops.model._T'),
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
]

# Pull in fix from https://github.com/sphinx-doc/sphinx/pull/11222/files to fix
# "invalid signature for autoattribute ('ops.pebble::ServiceDict.backoff-delay')"

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
