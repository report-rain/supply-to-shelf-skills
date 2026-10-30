"""Uniform error contract: stdout keeps machine-readable JSON, humans read stderr."""

import json
import sys

_JSON_MODE = False


def set_json_mode(enabled):
    global _JSON_MODE
    _JSON_MODE = bool(enabled)


def is_json_mode():
    return _JSON_MODE


class CliFailure(Exception):
    """A controlled, user-facing failure with an exit code and payload."""

    def __init__(self, message, code=2, missing=None, status="INPUT_MISSING"):
        super().__init__(message)
        self.message = message
        self.code = code
        self.missing = list(missing or [])
        self.status = status


def fail(message, code=2, missing=None, status="INPUT_MISSING"):
    raise CliFailure(message, code=code, missing=missing, status=status)


def emit_json(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def emit_failure(failure):
    if _JSON_MODE:
        emit_json(
            {
                "status": failure.status,
                "missing": failure.missing,
                "message": failure.message,
            }
        )
    sys.stderr.write("[{}] {}\n".format(failure.status, failure.message))


def run_main(entry):
    """Execute entry(); turn CliFailure into the documented output and exit code."""
    try:
        return entry()
    except CliFailure as exc:
        emit_failure(exc)
        return exc.code
