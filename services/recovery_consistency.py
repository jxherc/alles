"""Short lock for state that must agree with a recovery snapshot."""

import threading

recovery_consistency_lock = threading.RLock()
