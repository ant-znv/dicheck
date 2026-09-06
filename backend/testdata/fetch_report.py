import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8787/api/jobs/769b3d9e5a1a") as resp:
    raw = resp.read()
d = json.loads(raw.decode("utf-8"))
r = d["results"][0]
print("job:", d["status"], "| file:", r["status"], "| verdict:", r["summaryVerdict"], "| error:", r["error"])
with open(r"\backend\testdata\last_report.md", "w", encoding="utf-8") as f:
    f.write(r["report"])
print("saved chars:", len(r["report"]))
