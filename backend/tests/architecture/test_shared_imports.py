import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Imports every apps.shared module in a fresh interpreter that refuses to load a forbidden module.
PROBE = """
import importlib, pkgutil, sys

FORBIDDEN = ("apps.stores", "apps.accounts")

class RefuseForbidden:
    def find_spec(self, name, path=None, target=None):
        if any(name == root or name.startswith(root + ".") for root in FORBIDDEN):
            raise ImportError(f"apps.shared imported {name}")
        return None

sys.meta_path.insert(0, RefuseForbidden())

import apps.shared
for module in pkgutil.walk_packages(apps.shared.__path__, "apps.shared."):
    importlib.import_module(module.name)
"""


def test_importing_shared_loads_neither_stores_nor_accounts():
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


# Imports every apps.shared.domain module, ports included, refusing Django and DRF.
DOMAIN_PROBE = """
import importlib, pkgutil, sys

FORBIDDEN = ("django", "rest_framework")

class RefuseForbidden:
    def find_spec(self, name, path=None, target=None):
        if any(name == root or name.startswith(root + ".") for root in FORBIDDEN):
            raise ImportError(f"apps.shared.domain imported {name}")
        return None

sys.meta_path.insert(0, RefuseForbidden())

import apps.shared.domain
for module in pkgutil.walk_packages(apps.shared.domain.__path__, "apps.shared.domain."):
    importlib.import_module(module.name)
"""


def test_the_shared_domain_and_its_ports_import_no_django():
    result = subprocess.run(
        [sys.executable, "-c", DOMAIN_PROBE],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
