import json, time, urllib.request, ssl, certifi, re
from pathlib import Path
ctx = ssl.create_default_context(cafile=certifi.where())
UA = {"User-Agent": "Mozilla/5.0 (compatible; telecom-india-study/0.1; personal non-commercial)"}
rows = json.load(open("data/raw/report_index.json"))
seen, done = set(), 0
for r in rows:
    if r["url"] in seen: continue
    seen.add(r["url"])
    out = Path("data/raw") / r["url"].rsplit("/", 1)[1]
    if out.exists() or (out.name == "PR_No125of2026_0.pdf" and Path("data/raw/pr125.pdf").exists()):
        if not out.exists(): Path("data/raw/pr125.pdf").rename(out)
        done += 1; continue
    for attempt in range(3):
        try:
            data = urllib.request.urlopen(urllib.request.Request(r["url"], headers=UA), context=ctx, timeout=300).read()
            out.write_bytes(data); done += 1
            print(f"{done:2d} {r['title'][-28:]:28s} {len(data)/1e6:5.1f} MB", flush=True)
            break
        except Exception as e:
            print("retry", r["url"], e, flush=True); time.sleep(10)
    time.sleep(4)
print("done", done, "of", len(seen))
