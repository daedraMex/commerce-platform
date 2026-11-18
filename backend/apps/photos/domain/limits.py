"""Limits enforced on a staff photo before it is read into memory.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
