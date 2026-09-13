"""Chess variants that TALOS adds on top of python-chess."""

from .anarchchess import (ACTIVE, ANARCHY, CURATED, PRESETS, RULE_BOOK,
                          AnarchBoard, AnarchRules, active_rules, is_special,
                          make_board, reset_active_rules, set_active_rules)

__all__ = ["AnarchBoard", "AnarchRules", "CURATED", "ANARCHY", "PRESETS",
           "ACTIVE", "RULE_BOOK", "is_special", "make_board",
           "active_rules", "set_active_rules", "reset_active_rules"]
