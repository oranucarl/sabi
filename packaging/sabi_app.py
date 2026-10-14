"""Entry point for the packaged app."""

import multiprocessing
import sys

# Libraries SAbi uses start helper processes; in a frozen app those must not re-launch SAbi itself.
multiprocessing.freeze_support()

from sabi.__main__ import main  # noqa: E402

sys.exit(main())
