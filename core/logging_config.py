import logging
import sys


class _BelowWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.WARNING


def configure_logging(level: str = "INFO") -> None:
    """DEBUG/INFO go to stdout, WARNING+ go to stderr.

    Railway (and most log platforms) infer severity from which stream a
    line came from, not its content - logging.basicConfig()'s default
    handler writes everything to stderr, so routine INFO lines (e.g. every
    outbound httpx request) were showing up as "Error" in the Railway
    dashboard. Splitting by level here keeps that stream-based heuristic
    aligned with actual severity, instead of just moving everything to
    stdout (which would hide genuine errors/exceptions too).
    """
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(_BelowWarning())
    stdout_handler.setLevel(resolved_level)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(resolved_level)
    root.handlers = [stdout_handler, stderr_handler]
