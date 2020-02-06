import logging


class JujuLogHandler(logging.Handler):
    """A handler for sending logs to Juju via juju-log."""

    def __init__(self, model_backend, level=logging.DEBUG):
        super().__init__(level)
        self.model_backend = model_backend

    def emit(self, record):
        self.model_backend.juju_log(record.levelname, self.format(record))


def setup_default_logging(model_backend):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(JujuLogHandler(model_backend))
