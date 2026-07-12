#!/usr/bin/env python3
"""Reconcile this profile's generated view from profile.yaml and public sources.

No packages are required. The tiny YAML reader supports only the declarative
subset used here: mappings, indentation, and lists.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".profile-state.json"


def scalar(value: str) -> Any:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "~"}:
        return None
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a deliberately small, dependency-free YAML subset."""
    rows: list[tuple[int, str]] = []
    for raw in path.read_text().splitlines():
        clean = raw.split(" #", 1)[0].rstrip()
        if clean.strip() and not clean.lstrip().startswith("#"):
            rows.append((len(clean) - len(clean.lstrip()), clean.lstrip()))

    def block(index: int, indent: int) -> tuple[Any, int]:
        is_list = rows[index][1].startswith("- ")
        result: Any = [] if is_list else {}
        while index < len(rows) and rows[index][0] == indent:
            _, text = rows[index]
            if is_list:
                if not text.startswith("- "):
                    break
                item = text[2:].strip()
                index += 1
                if ":" in item:
                    key, value = item.split(":", 1)
                    entry: dict[str, Any] = {key.strip(): scalar(value)}
                    if index < len(rows) and rows[index][0] > indent:
                        nested, index = block(index, rows[index][0])
                        if isinstance(nested, dict):
                            entry.update(nested)
                    result.append(entry)
                else:
                    result.append(scalar(item))
            else:
                if ":" not in text:
                    raise ValueError(f"Expected key: value, got {text!r}")
                key, value = text.split(":", 1)
                index += 1
                if value.strip():
                    result[key.strip()] = scalar(value)
                elif index < len(rows) and rows[index][0] > indent:
                    result[key.strip()], index = block(index, rows[index][0])
                else:
                    result[key.strip()] = {}
        return result, index

    return block(0, rows[0][0])[0] if rows else {}


def request_json(url: str) -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "harsh-control-plane"}
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=12) as response:
        return json.load(response)


def fetch_changes(profile: dict[str, Any]) -> list[dict[str, str]]:
    changes = []
    for system in profile["systems"]:
        commits = request_json(f"https://api.github.com/repos/{system['repository']}/commits?per_page=1")
        if commits:
            commit = commits[0]["commit"]
            changes.append({
                "date": commit["author"]["date"][:10],
                "system": system["name"],
                "message": commit["message"].splitlines()[0][:88],
                "url": commits[0]["html_url"],
            })
    return sorted(changes, key=lambda entry: entry["date"], reverse=True)[:4]


def fetch_writing() -> dict[str, str] | None:
    request = urllib.request.Request(
        "https://medium.com/feed/@harshdaga18",
        headers={"User-Agent": "Mozilla/5.0 (compatible; harsh-control-plane/1.0)", "Accept": "application/rss+xml, application/xml"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        root = ET.fromstring(response.read())
    item = root.find("./channel/item")
    if item is None:
        return None
    return {"title": item.findtext("title", "Untitled"), "url": item.findtext("link", "")}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render_svg(profile: dict[str, Any], state: dict[str, Any], theme: str) -> str:
    dark = theme == "dark"
    palette = ({"bg": "#0b1016", "panel": "#101923", "line": "#2e4152", "text": "#e6edf3", "muted": "#91a4b7", "accent": "#44d6a8", "grid": "#1b2936"} if dark else
               {"bg": "#f7fafc", "panel": "#ffffff", "line": "#b8c7d3", "text": "#15212b", "muted": "#536675", "accent": "#087f5b", "grid": "#dce6ed"})
    systems = profile["systems"]
    changes = state.get("recent_changes", [])
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="620" viewBox="0 0 1200 620" role="img" aria-labelledby="title desc">',
        f'<title id="title">{esc(profile["operator"]["name"])} control plane</title><desc id="desc">Generated engineering control plane showing operating scope, systems, and recent public changes.</desc>',
        f'<rect width="1200" height="620" fill="{palette["bg"]}"/><path d="M0 40H1200M0 80H1200M0 120H1200M0 160H1200M0 200H1200M0 240H1200M0 280H1200M0 320H1200M0 360H1200M0 400H1200M0 440H1200M0 480H1200M0 520H1200M0 560H1200M0 600H1200" stroke="{palette["grid"]}" stroke-width="1"/>',
        f'<rect x="18" y="18" width="1164" height="584" rx="8" fill="{palette["panel"]}" stroke="{palette["line"]}" stroke-width="2"/>',
        f'<path d="M18 62H1182" stroke="{palette["line"]}"/><circle cx="40" cy="40" r="5" fill="{palette["accent"]}"/><text x="56" y="46" fill="{palette["text"]}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="18" font-weight="700">harsh/control-plane</text>',
    ]
    facts = [("OPERATOR", profile["operator"]["name"]), ("DOMAIN", profile["operator"]["domain"]), ("PRODUCTION", profile["operator"]["production"]), ("PRINCIPLE", profile["operator"]["principle"])]
    for number, (label, value) in enumerate(facts):
        y = 98 + number * 27
        lines.append(f'<text x="48" y="{y}" fill="{palette["muted"]}" font-family="ui-monospace, monospace" font-size="14">{label}</text><text x="210" y="{y}" fill="{palette["text"]}" font-family="ui-monospace, monospace" font-size="14">{esc(value)}</text>')
    lines.append(f'<text x="48" y="230" fill="{palette["accent"]}" font-family="ui-monospace, monospace" font-size="15" font-weight="700">SYSTEMS / DEPLOYED COMPONENTS</text>')
    for number, system in enumerate(systems):
        y = 262 + number * 35
        lines.append(f'<circle cx="56" cy="{y - 5}" r="5" fill="{palette["accent"]}"/><text x="74" y="{y}" fill="{palette["text"]}" font-family="ui-monospace, monospace" font-size="16" font-weight="700">{esc(system["name"])}</text><text x="250" y="{y}" fill="{palette["muted"]}" font-family="ui-monospace, monospace" font-size="14">{esc(system["class"])}</text>')
    lines.append(f'<path d="M48 418H1152" stroke="{palette["line"]}"/><text x="48" y="452" fill="{palette["accent"]}" font-family="ui-monospace, monospace" font-size="15" font-weight="700">RECENT PUBLIC CHANGES</text>')
    if changes:
        for number, change in enumerate(changes[:3]):
            y = 485 + number * 28
            lines.append(f'<text x="48" y="{y}" fill="{palette["muted"]}" font-family="ui-monospace, monospace" font-size="13">{esc(change["date"])}</text><text x="150" y="{y}" fill="{palette["text"]}" font-family="ui-monospace, monospace" font-size="13" font-weight="700">{esc(change["system"])}</text><text x="315" y="{y}" fill="{palette["text"]}" font-family="ui-monospace, monospace" font-size="13">{esc(change["message"])}</text>')
    else:
        lines.append(f'<text x="48" y="485" fill="{palette["muted"]}" font-family="ui-monospace, monospace" font-size="13">awaiting first successful public-repository reconciliation</text>')
    lines.append(f'<text x="48" y="572" fill="{palette["muted"]}" font-family="ui-monospace, monospace" font-size="12">generated from profile.yaml · reproducible by default · last state is committed</text></svg>')
    document = "\n".join(lines) + "\n"
    return (ROOT / "templates" / "dashboard.svg.j2").read_text().replace("{{ svg }}", document)


def render_readme(profile: dict[str, Any], state: dict[str, Any]) -> str:
    template = (ROOT / "templates" / "README.md.j2").read_text()
    components = "\n\n".join(f"### SYSTEM: [{item['slug']}](https://github.com/{item['repository']})\n\n```text\nclass        {item['class']}\nobjective    {item['objective']}\nmechanism    {item['mechanism']}\nproperties   {item['properties']}\nstate        {item['state']}\n```" for item in profile["systems"])
    changes = state.get("recent_changes", [])
    recent = "\n".join(f"- `{item['date']}`  **[{item['system']}]({item['url']})** — {item['message']}" for item in changes) or "_Awaiting the first successful repository reconciliation._"
    principles = "\n".join(f"- {entry}" for entry in profile["principles"])
    op_log = "\n".join(f"- {entry}" for entry in profile["operator_log"]["entries"])
    writing = state.get("latest_writing")
    latest = f"- [{writing['title']}]({writing['url']})" if writing else "_No writing has been synchronized yet; browse the [writing archive]({})._".format(profile["links"]["writing"])
    model = "\n".join(f"├── {entry}" for entry in profile["system_model"][:-1]) + "\n└── " + profile["system_model"][-1]
    values = {"components": components, "recent_changes": recent, "principles": principles, "operator_log": op_log, "latest_writing": latest, "system_model": model}
    for section, content in (("operator", profile["operator"]), ("links", profile["links"]), ("operator_log", profile["operator_log"])):
        for key, value in content.items():
            values[f"{section}.{key}"] = value
    return re.sub(r"{{\s*([\w.]+)\s*}}", lambda match: str(values.get(match.group(1), match.group(0))), template)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Fetch public GitHub and Medium state before rendering")
    args = parser.parse_args()
    profile = load_yaml(ROOT / "profile.yaml")
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    if args.refresh:
        try:
            changes = fetch_changes(profile)
            if changes:
                state["recent_changes"] = changes
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as error:
            print(f"GitHub refresh skipped: {error}")
        try:
            writing = fetch_writing()
            if writing:
                state["latest_writing"] = writing
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as error:
            print(f"Medium refresh skipped: {error}")
        state["updated_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "control-plane-dark.svg").write_text(render_svg(profile, state, "dark"))
    (ROOT / "assets" / "control-plane-light.svg").write_text(render_svg(profile, state, "light"))
    (ROOT / "README.md").write_text(render_readme(profile, state))
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
