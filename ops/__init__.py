# note because the first import of ops can be from any of the
# namespace-providing packages, this __init__.py can't have any code
# beyond the extend_path call.

# import with underscore to keep the 'public' things clean
from pkgutil import extend_path as _extend_path
__path__ = _extend_path(__path__, __name__)
