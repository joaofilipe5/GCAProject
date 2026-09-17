"""Compatibility entry point for the final Model 1 sensitivity runner.

The original runner referred to wind/solar price constants removed from ghsc.py.
Use the final project runner with the current pmin/pmax model interface.
"""

import argparse

from ghsc_sensitivity_dashboard import main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Model 1 sensitivity scenarios")
    parser.add_argument(
        "--no-plots", action="store_true",
        help="Write the results CSV without creating PNG charts",
    )
    args = parser.parse_args()
    main(create_plots=not args.no_plots)
