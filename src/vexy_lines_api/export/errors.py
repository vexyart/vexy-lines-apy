# this_file: vexy-lines-apy/src/vexy_lines_api/export/errors.py

from __future__ import annotations


class ExportAborted(Exception):
    pass


class ExportValidationError(Exception):
    pass
