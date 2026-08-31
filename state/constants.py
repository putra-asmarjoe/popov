"""Konstanta bersama untuk investigasi otonom (CHATFLOW V2.1).

Dipakai oleh correlation_agent (Tahap 1), router Tahap 4 (graph/workflow.py),
dan response_agent (blok confidence). Jangan hardcode nilai ini di file lain.
"""

import os

# Threshold confidence di bawah nilai ini dianggap "belum cukup yakin"
CONFIDENCE_THRESHOLD: float = 0.80

# Maksimal berapa kali autonomous loop boleh berjalan per tiket
AUTO_LOOP_MAX: int = 1

# Feature flag — matikan di staging untuk debugging yang lebih mudah.
# Bisa di-override via env POPOV_AUTONOMOUS_LOOP=false (rollback cepat tanpa deploy).
AUTONOMOUS_LOOP_ENABLED: bool = os.getenv("POPOV_AUTONOMOUS_LOOP", "true").lower() not in ("0", "false", "no")
