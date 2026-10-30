"""Argument parser whose errors honour the JSON/stderr contract."""

import argparse
import sys

from .errors import fail


class CliArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, error_exit_code=2, **kwargs):
        self.error_exit_code = error_exit_code
        super().__init__(*args, **kwargs)

    def error(self, message):
        self.print_usage(sys.stderr)
        fail("参数错误：" + message, code=self.error_exit_code, missing=[])
