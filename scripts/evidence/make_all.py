"""Regenerate every evidence-pack figure and data file. Usage: python scripts/evidence/make_all.py [module ...]"""

import importlib
import sys

MODULES = [
    "fig_a_expb003",
    "fig_b_gate",
    "fig_c_g2b_dev",
    "fig_d_terms",
    "fig_e_categories",
    "fig_f_literature",
    "fig_g_frontA",
    "verify_numbers",
    "make_tables",
]

if __name__ == "__main__":
    for name in sys.argv[1:] or MODULES:
        importlib.import_module(name).main()
