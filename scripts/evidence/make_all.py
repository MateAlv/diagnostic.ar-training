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
    "fig_h_l1_frontier",
    "fig_i_l4_strategies",
    "fig_j_expb004_forest",
    "fig_k_expb005",
    "verify_numbers",
    "make_tables",
]

if __name__ == "__main__":
    for name in sys.argv[1:] or MODULES:
        importlib.import_module(name).main()
