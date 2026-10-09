"""Probe 2: download the Canada PPID extracts and the France E-Phy zip, then inspect
columns and look for the pilot products / active microorganisms.
Why: confirm the open files really contain product, status, uses and label links we need."""
import sys, io, zipfile, re, hashlib, json, datetime as dt
import httpx, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
RAW = Path("data/raw/probe"); RAW.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "lpc-regwatch-probe/0.1 (hackathon prototype)"}
KEYS = ["CONTANS", "PRESTOP", "MET52", "MET 52", "LALSTOP", "LALGUARD", "LALFRESH", "MITAXION",
        "CONIOTHYRIUM", "CLONOSTACHYS", "GLIOCLADIUM", "METARHIZIUM"]
PAT = re.compile("|".join(KEYS), re.I)

def fetch(url, name):
    p = RAW / name
    if p.exists() and p.stat().st_size > 0:
        print(f"[cached] {name} {p.stat().st_size/1e6:.1f}MB"); return p
    t0 = dt.datetime.now(dt.timezone.utc)
    with httpx.stream("GET", url, headers=H, timeout=300, follow_redirects=True) as r:
        r.raise_for_status(); data = b"".join(r.iter_bytes())
    p.write_bytes(data)
    meta = {"url": url, "collected_at": t0.isoformat(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": r.headers.get("content-type"), "status": r.status_code}
    (RAW / (name + ".meta.json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[downloaded] {name} {len(data)/1e6:.1f}MB ct={meta['content_type']}"); return p

def read_csv_any(path_or_bytes, **kw):
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try: return pd.read_csv(path_or_bytes, encoding=enc, dtype=str, low_memory=False, **kw)
        except UnicodeDecodeError:
            if hasattr(path_or_bytes, "seek"): path_or_bytes.seek(0)
    raise RuntimeError("no encoding worked")

def scan(df, label):
    print(f"\n--- {label}: {df.shape[0]} rows x {df.shape[1]} cols")
    print("columns:", list(df.columns))
    mask = df.apply(lambda col: col.astype(str).str.contains(PAT, na=False)).any(axis=1)
    hits = df[mask]
    print(f"pilot-related rows: {len(hits)}")
    if len(hits): print(hits.head(40).to_string(max_colwidth=40))
    return hits

CA = "https://pest-control.canada.ca/pesticide-registry-api/api/extract/"
for ext in ("product", "ingredient", "label", "application"):
    try:
        p = fetch(CA + ext, f"ca_{ext}.csv"); df = read_csv_any(p); scan(df, f"CANADA {ext}")
    except Exception as e: print(f"!! CANADA {ext}: {type(e).__name__}: {e}")

try:
    p = fetch("https://static.data.gouv.fr/resources/donnees-ouvertes-du-catalogue-e-phy-des-produits-phytopharmaceutiques-matieres-fertilisantes-et-supports-de-culture-adjuvants-produits-mixtes-et-melanges/20261007-225319/decisionamm-intrant-format-csv-20261008-utf8.zip", "fr_ephy_utf8.zip")
    z = zipfile.ZipFile(p); print("\nE-PHY zip members:"); [print("  ", i.filename, f"{i.file_size/1e6:.1f}MB") for i in z.infolist()]
    for i in z.infolist():
        if not i.filename.lower().endswith(".csv"): continue
        df = read_csv_any(io.BytesIO(z.read(i)), sep=";"); scan(df, f"FRANCE {i.filename}")
except Exception as e: print(f"!! FRANCE: {type(e).__name__}: {e}")
