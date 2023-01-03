import logging
import os

logger = logging.getLogger("ops-scenario")
logger.setLevel(os.getenv("OPS_SCENARIO_LOGGING", "WARNING"))
