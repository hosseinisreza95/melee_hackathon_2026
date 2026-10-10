#!/usr/bin/env python3
"""Generate the Power Platform custom-connector definition (Swagger 2.0 / OpenAPI 2.0 JSON) from the live
FastAPI schema. Power Automate / Power Apps / Copilot Studio custom connectors still import OpenAPI 2.0,
so we down-convert the contract endpoints (+ export and ask) into m365/apiDefinition.swagger.json.

Usage: python scripts/export_m365_connector.py --host 37.187.176.97 --base-path /api
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

KEEP = {"/health", "/products", "/products/{productId}/registrations", "/compare", "/ask", "/products/{productId}/aliases",
        "/expiring", "/changes", "/export.csv", "/sources"}


def _ref(name: str) -> dict:
    return {"$ref": f"#/definitions/{name}"}


def convert_schema(s: dict, defs: dict) -> dict:
    """OpenAPI 3.1 -> Swagger 2.0 schema subset (nullable unions, anyOf, refs)."""
    if "$ref" in s:
        return {"$ref": s["$ref"].replace("#/components/schemas/", "#/definitions/")}
    if "anyOf" in s:
        non_null = [x for x in s["anyOf"] if x.get("type") != "null"]
        out = convert_schema(non_null[0], defs) if non_null else {"type": "string"}
        out["x-nullable"] = True
        return out
    out = {}
    t = s.get("type")
    if isinstance(t, list):
        nn = [x for x in t if x != "null"]
        out["type"] = nn[0] if nn else "string"
        out["x-nullable"] = True
    elif t:
        out["type"] = t
    for k in ("format", "enum", "description", "default", "minimum", "maximum", "pattern", "title"):
        if k in s:
            out[k] = s[k]
    if "const" in s:
        out["enum"] = [s["const"]]
    if "properties" in s:
        out["properties"] = {k: convert_schema(v, defs) for k, v in s["properties"].items()}
    if "required" in s:
        out["required"] = s["required"]
    if "items" in s:
        out["items"] = convert_schema(s["items"], defs)
    if "additionalProperties" in s and isinstance(s["additionalProperties"], dict):
        out["additionalProperties"] = convert_schema(s["additionalProperties"], defs)
    return out


def main(host: str, base_path: str, scheme: str) -> Path:
    from lpc_regwatch.api.app import app

    oa = app.openapi()
    defs = {name: convert_schema(sch, {}) for name, sch in oa.get("components", {}).get("schemas", {}).items()}
    paths = {}
    for path, ops in oa["paths"].items():
        if path not in KEEP:
            continue
        paths[path] = {}
        for method, op in ops.items():
            params = []
            for p in op.get("parameters", []):
                sch = convert_schema(p.get("schema", {}), defs)
                params.append({"name": p["name"], "in": p["in"], "required": p.get("required", False), "description": p.get("description", ""),
                               **{k: v for k, v in sch.items() if k in ("type", "format", "enum", "default", "pattern")}, **({"type": "string"} if "type" not in sch else {})})
            body = op.get("requestBody")
            if body:
                sch = body["content"]["application/json"]["schema"]
                params.append({"name": "body", "in": "body", "required": True, "schema": convert_schema(sch, defs)})
            responses = {}
            for code, r in op.get("responses", {}).items():
                resp = {"description": r.get("description", "")}
                content = r.get("content", {})
                if "application/json" in content and "schema" in content["application/json"]:
                    resp["schema"] = convert_schema(content["application/json"]["schema"], defs)
                responses[code] = resp
            paths[path][method] = {"operationId": op["operationId"], "summary": op.get("summary", op["operationId"]),
                                   "description": (op.get("description") or op.get("summary") or "")[:500], "parameters": params, "responses": responses,
                                   "produces": ["text/csv"] if path.endswith(".csv") else ["application/json"],
                                   "x-ms-visibility": "important" if path in ("/compare", "/ask", "/products") else "advanced"}
    swagger = {
        "swagger": "2.0",
        "info": {"title": "LPC Regulatory Watch", "version": oa["info"]["version"],
                 "description": "Regulatory-watch API (official sources CA/US/FR/BR). Not an official regulatory source: every answer "
                                "carries evidence (source, URL, collection time, validation status) and a disclaimer. No result is not proof of no registration.",
                 "contact": {"name": "LPC hackathon team"}},
        "host": host, "basePath": base_path, "schemes": [scheme], "consumes": ["application/json"], "produces": ["application/json"],
        "paths": paths, "definitions": defs,
        "securityDefinitions": {"api_key": {"type": "apiKey", "in": "header", "name": "X-API-Key",
                                             "description": "Not enforced by the tool; placeholder for the Entra ID / API Management design in m365/README.md"}},
        "security": [],
        "x-ms-connector-metadata": [{"propertyName": "Website", "propertyValue": f"{scheme}://{host}{base_path}/docs"},
                                    {"propertyName": "Privacy policy", "propertyValue": f"{scheme}://{host}{base_path}/sources"},
                                    {"propertyName": "Categories", "propertyValue": "Data;Business Intelligence"}],
    }
    out = ROOT / "m365" / "apiDefinition.swagger.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(swagger, indent=2, ensure_ascii=False), encoding="utf-8")
    props = {"properties": {"connectionParameters": {}, "iconBrandColor": "#2e7d32", "capabilities": [], "publisher": "LPC hackathon team",
                            "stackOwner": "Lallemand Plant Care", "policyTemplateInstances": []}}
    (ROOT / "m365" / "apiProperties.json").write_text(json.dumps(props, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost:8000")
    ap.add_argument("--base-path", default="")
    ap.add_argument("--scheme", default="http")
    a = ap.parse_args()
    p = main(a.host, a.base_path or "/", a.scheme)
    d = json.loads(p.read_text(encoding="utf-8"))
    print("written", p, "| operations:", sum(len(v) for v in d["paths"].values()), "| definitions:", len(d["definitions"]))
