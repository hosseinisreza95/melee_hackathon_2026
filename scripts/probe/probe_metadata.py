"""Probe 1: fetch dataset metadata (resource list + download URLs) from the official
open-data portals for Canada (CKAN) and France (data.gouv.fr).
Why: before writing collectors we need the exact file URLs, formats and sizes."""
import json, sys, httpx
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
OUT = Path("data/raw/probe"); OUT.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "lpc-regwatch-probe/0.1 (hackathon prototype)"}

def ckan_canada():
    url = "https://open.canada.ca/data/api/3/action/package_show"
    r = httpx.get(url, params={"id": "e10b0d6e-04ac-4014-a64a-666c3874bbe0"}, headers=H, timeout=60, follow_redirects=True)
    r.raise_for_status(); d = r.json()["result"]
    (OUT / "ca_ppid_package.json").write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print("== CANADA PPID ==", d.get("title"), "| frequency:", d.get("frequency"), "| modified:", d.get("metadata_modified"))
    for res in d["resources"]:
        name = res.get("name") or res.get("name_translated", {}).get("en")
        print(f"  - {name!s:70.70} | {res.get('format'):5} | lang={res.get('language')} | {res.get('url')}")

def datagouv_ephy():
    slug = "donnees-ouvertes-du-catalogue-e-phy-des-produits-phytopharmaceutiques-matieres-fertilisantes-et-supports-de-culture-adjuvants-produits-mixtes-et-melanges"
    r = httpx.get(f"https://www.data.gouv.fr/api/1/datasets/{slug}/", headers=H, timeout=60, follow_redirects=True)
    r.raise_for_status(); d = r.json()
    (OUT / "fr_ephy_dataset.json").write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n== FRANCE E-PHY ==", d.get("title"), "| license:", d.get("license"), "| frequency:", d.get("frequency"), "| last_update:", d.get("last_update"))
    for res in d["resources"]:
        size = res.get("filesize"); size = f"{size/1e6:.1f}MB" if size else "?"
        print(f"  - {res.get('title')!s:80.80} | {res.get('format'):5} | {size:>8} | {res.get('last_modified','')[:10]} | {res.get('url')}")

if __name__ == "__main__":
    for fn in (ckan_canada, datagouv_ephy):
        try: fn()
        except Exception as e: print(f"!! {fn.__name__} failed: {type(e).__name__}: {e}")
