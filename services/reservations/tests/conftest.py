import os
import sys

# Let the tests import the service as `app`, whichever folder pytest is started from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))