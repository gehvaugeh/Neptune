import argparse
import sys

BLUE = "\033[1;34m"
CYAN = "\033[1;36m"
RESET = "\033[0m"

NEPTUNE_ASCII = rf"""
{BLUE}
    _   __            __
   / | / /__  ____   / /_ __  __ ____   ___
  /  |/ // _ \/ __ \ / __// / / // __ \ / _ \
 / /|  //  __/ /_/ // /_ / /_/ // / / //  __/
/_/ |_/ \___/ .___/ \__/ \__,_//_/ /_/ \___/
            /_/
{RESET}
"""

def setup_parser(description: str):
    parser = argparse.ArgumentParser(
        description=NEPTUNE_ASCII + description,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    return parser

def check_args(parser: argparse.ArgumentParser):
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)
