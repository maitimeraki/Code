#!/usr/bin/env python3
"""Debug app startup to find why UI isn't rendering."""

import asyncio
import traceback
import sys

print("[DEBUG] Python version:", sys.version)
print("[DEBUG] Starting app import...")

try:
    from harness.app import HarnessApp
    print("[DEBUG] HarnessApp imported successfully")

    app = HarnessApp()
    print("[DEBUG] HarnessApp instance created")
    print(f"[DEBUG] UI._live attribute exists: {hasattr(app.ui, '_live')}")
    print(f"[DEBUG] UI._dirty value: {app.ui._dirty}")

    print("[DEBUG] Calling app.run()...")
    asyncio.run(app.run())

except KeyboardInterrupt:
    print("\n[DEBUG] Interrupted by user")
except Exception as e:
    print(f"[ERROR] {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)
