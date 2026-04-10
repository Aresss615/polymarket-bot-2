import requests
from datetime import datetime, timezone

# Fetch markets sorted by soonest expiry
resp = requests.get(
    "https://gamma-api.polymarket.com/markets",
    params={"active": "true", "closed": "false", "limit": 100, "order": "endDate", "ascending": "true"},
    timeout=10,
)
data = resp.json()
now = datetime.now(timezone.utc)
print("Soonest-expiry markets:")
for m in data[:15]:
    end = m.get("endDateIso", m.get("endDate", ""))
    print(f"  {end[:16]}  {m.get('question','')[:60]}")
