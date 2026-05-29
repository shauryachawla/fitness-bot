"""Quick test to verify biometric data fetching from Google Health API."""
import json

from clients.google_health import fetch_biometrics

data = fetch_biometrics(days=7)

for key, points in data.items():
    print(f"\n--- {key} ({len(points)} points) ---")
    if points:
        print(json.dumps(points[:3], indent=2, default=str))
    else:
        print("  (empty)")
