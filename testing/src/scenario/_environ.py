import os

def wrap_charm_errors(default: str = 'True') -> bool:
    """Return whether scenario should wrap charm errors with ``UncaughtCharmError``."""
    return os.getenv('SCENARIO_WRAP_CHARM_ERRORS', default).capitalize() != 'False'
