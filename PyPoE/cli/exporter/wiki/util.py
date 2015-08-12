"""
Path     PyPoE/cli/exporter/wiki/util.py
Name     Utility functions for wiki exporters
Version  1.00.000
Revision $Id$
Author   [#OMEGA]- K2

INFO

Utility functions for wiki exporters.


AGREEMENT

See PyPoE/LICENSE


TODO

...
"""

# =============================================================================
# Imports
# =============================================================================

# Python
import os
import hashlib

# self
from PyPoE.poe.path import PoEPath
from PyPoE.cli.config import SetupError
from PyPoE.cli.exporter import config

# =============================================================================
# Globals
# =============================================================================

__all__ = ['get_content_ggpk_path', 'get_content_ggpk_hash', 'check_hash']

# =============================================================================
# Functions
# =============================================================================

def get_content_ggpk_path():
    args = config.get_option('version'), config.get_option('distributor')
    paths = PoEPath(*args).get_installation_paths()

    if not paths:
        raise SetupError('No PoE Installation found.')

    return os.path.join(paths[0], 'content.ggpk')

def get_content_ggpk_hash():
    ggpk = get_content_ggpk_path()
    with open(ggpk, 'rb') as f:
        data = f.read(2**16)

    return hashlib.md5(data).hexdigest()

def check_hash():
    hash_old = config.get_setup_variable('temp_dir', 'hash')
    hash_new = get_content_ggpk_hash()

    if hash_old == hash_new:
        return True

    config.set_setup_variable('temp_dir', 'performed', False)
    return False