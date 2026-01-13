import logging
import sys
import json
from typing import Any


class PrettyFormatter(logging.Formatter):
    """
    Logging formatter that pretty-prints dict / list payloads
    when they are passed as the log message.
    """

    def format(self, record: logging.LogRecord) -> str:
        msg = record.msg

        # If the message itself is a dict / list, pretty print it
        if isinstance(msg, (dict, list)):
            record.msg = json.dumps(
                msg,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
            record.args = ()

        return super().format(record)


def setup_logging(level: int = logging.INFO):
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = PrettyFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


def log_pretty(
    logger: logging.Logger,
    title: str,
    payload: Any,
    level: int = logging.INFO,
):
    """
    Unified helper for pretty logging complex objects (e.g. ccxt ticker).

    Usage:
        log_pretty(logger, "ticker raw", ticker_dict)
    """
    logger.log(
        level,
        "%s:\n%s",
        title,
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
    )

def _logger_pretty(self, payload):
    if isinstance(payload, (dict, list)):
        self.info(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
    else:
        self.info(payload)


logging.Logger.pretty = _logger_pretty