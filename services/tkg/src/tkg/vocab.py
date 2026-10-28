"""Thin re-export: the TKG vocabularies live in finsight_shared.tkg_vocab (guide T5)."""
from finsight_shared.tkg_vocab import *  # noqa: F401,F403
from finsight_shared.tkg_vocab import (  # noqa: F401
    ACTORS, DRIVERS, MAGNITUDE_MAP, RELATIONS, RELATION_NAMES, Driver, RelationType,
    get_driver_sign, is_valid_actor, is_valid_driver, is_valid_relation,
)
