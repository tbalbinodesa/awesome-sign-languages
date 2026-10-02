#!/usr/bin/env python3
"""Validate the resource data and generate the English and Portuguese guides.

Single source of truth:

- ``data/resources.json``: one record per resource, with a name and description
  in every guide language plus the facts the guides must be able to vouch for.
- ``data/layout.json``: which resources each guide lists, under which headings.
  A subsection may also have an ``intro`` (text before its list), an ``after`` note
  (text after it) and an ``anchor`` (an explicit ``<a id>`` for in-page links).
- ``templates/<locale>.md``: the hand-written prose of each guide, with
  ``<!-- toc -->`` and ``<!-- resources -->`` placeholders.

Usage:
    python3 tools/build.py           # validate, then rewrite the README files
    python3 tools/build.py --check   # validate and fail if a README is stale

Only the Python standard library is used.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Guide locale -> generated file.
OUTPUTS = {"en": "README.md", "pt-BR": "README.pt-BR.md"}

# Sign languages the directory covers, by ISO 639-3 code. Every resource must
# name its language(s) from this list so nothing is labelled just "sign language".
LANGUAGES = {"ase": "American Sign Language", "bzs": "Brazilian Sign Language (Libras)"}

ACCESS = {"free", "free-with-registration", "paid"}
TRANSLATION_OUTPUTS = {"avatar", "human", "text"}

TOC_MARKER = "<!-- toc -->"
RESOURCES_MARKER = "<!-- resources -->"
# A leftover placeholder, not a word that merely contains these letters ("TODOS").
TODO_PATTERN = re.compile(r"\bTODO\b")
ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_PATTERN = re.compile(r"\]\((\S+?)\)")
HEADING_PATTERN = re.compile(r"^(#{1,6}) ", re.MULTILINE)


def load(root=ROOT):
    resources = json.loads((root / "data/resources.json").read_text(encoding="utf-8"))
    layout = json.loads((root / "data/layout.json").read_text(encoding="utf-8"))
    templates = {
        locale: (root / f"templates/{locale}.md").read_text(encoding="utf-8")
        for locale in OUTPUTS
    }
    return resources["resources"], layout, templates


# --- Validation -------------------------------------------------------------


def validate_resources(resources):
    errors = []
    seen_ids, seen_urls = set(), set()
    for index, resource in enumerate(resources):
        rid = resource.get("id")
        label = f"resource {rid!r}" if rid else f"resource #{index}"
        if not isinstance(rid, str) or not ID_PATTERN.match(rid):
            errors.append(f"{label}: id must be a lowercase-hyphenated slug")
        elif rid in seen_ids:
            errors.append(f"{label}: duplicate id")
        seen_ids.add(rid)

        url = resource.get("url", "")
        if url in seen_urls:
            errors.append(f"{label}: duplicate url {url}")
        seen_urls.add(url)
        if url.startswith("https://"):
            pass
        elif url.startswith("http://"):
            if not resource.get("insecure_http"):
                errors.append(
                    f"{label}: url is http://; use https:// or set "
                    '"insecure_http": true when the official site has no https'
                )
        else:
            errors.append(f"{label}: url must be an absolute http(s) URL")

        languages = resource.get("languages")
        if not isinstance(languages, list):
            errors.append(f"{label}: languages must be a list of codes")
        else:
            for code in languages:
                if code not in LANGUAGES:
                    errors.append(
                        f"{label}: unknown language code {code!r}; "
                        f"known: {', '.join(sorted(LANGUAGES))}"
                    )
            if not languages and not resource.get("language_independent"):
                errors.append(
                    f"{label}: name the sign language(s) it covers, or set "
                    '"language_independent": true for a general-purpose tool'
                )

        if not str(resource.get("maintainer", "")).strip():
            errors.append(f"{label}: maintainer is required (who is accountable for it?)")
        if resource.get("access") not in ACCESS:
            errors.append(f"{label}: access must be one of {sorted(ACCESS)}")

        translation = resource.get("translation")
        if translation is not None:
            if not str(translation.get("direction", "")).strip():
                errors.append(f"{label}: translation tools must state their direction")
            if translation.get("output") not in TRANSLATION_OUTPUTS:
                errors.append(
                    f"{label}: translation output must be one of {sorted(TRANSLATION_OUTPUTS)}"
                )

        for locale in OUTPUTS:
            text = resource.get(locale) or {}
            for field in ("name", "description"):
                value = str(text.get(field, "")).strip()
                if not value:
                    errors.append(f"{label}: missing {locale} {field}")
                elif TODO_PATTERN.search(value):
                    errors.append(f"{label}: {locale} {field} contains TODO")
        en = (resource.get("en") or {}).get("description")
        pt = (resource.get("pt-BR") or {}).get("description")
        if en and en == pt:
            errors.append(f"{label}: pt-BR description is identical to en; translate it")
    return errors


def validate_layout(resources, layout):
    errors = []
    by_id = {r.get("id"): r for r in resources}
    for locale in OUTPUTS:
        sections = layout.get(locale)
        if not sections:
            errors.append(f"layout: no sections for {locale}")
            continue
        placed = Counter()
        for section in sections:
            if not section.get("title"):
                errors.append(f"layout[{locale}]: section without a title")
            for sub in section.get("subsections", []):
                ids = sub.get("ids", [])
                placed.update(ids)
                for rid in ids:
                    if rid not in by_id:
                        errors.append(f"layout[{locale}]: unknown resource id {rid!r}")
                if any(by_id.get(rid, {}).get("translation") for rid in ids) and not sub.get("after"):
                    errors.append(
                        f"layout[{locale}]: subsection {sub.get('title')!r} lists a translation "
                        "tool but has no limitations note ('after')"
                    )
        for rid, count in placed.items():
            if count > 1:
                errors.append(f"layout[{locale}]: {rid!r} is listed {count} times")
        for rid in by_id:
            if rid not in placed:
                errors.append(f"layout[{locale}]: resource {rid!r} is missing from this guide")
    return errors


def validate_templates(templates):
    errors = []
    for locale, text in templates.items():
        for marker in (TOC_MARKER, RESOURCES_MARKER):
            if text.count(marker) != 1:
                errors.append(f"template[{locale}]: expected exactly one {marker}")
    # The prose is written by hand in each language, so check what can be checked:
    # same heading levels, same number of bullets, same external links. (Links to the
    # other guide are relative, so they are deliberately not compared.)
    reference, *others = list(templates.items())
    for locale, text in others:
        if _skeleton(text) != _skeleton(reference[1]):
            errors.append(
                f"template[{locale}]: heading structure, bullet count or links differ from "
                f"template[{reference[0]}]"
            )
    return errors


def _skeleton(text):
    headings = [m.group(1) for m in HEADING_PATTERN.finditer(text)]
    bullets = sum(1 for line in text.splitlines() if line.startswith("- ") and "](#" not in line)
    external = sorted(u for u in LINK_PATTERN.findall(text) if u.startswith("http"))
    return headings, bullets, external


def validate(resources, layout, templates):
    return (
        validate_resources(resources)
        + validate_layout(resources, layout)
        + validate_templates(templates)
    )


# --- Rendering --------------------------------------------------------------


def slug(title):
    """GitHub's heading anchor, so the generated table of contents links work."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def render(locale, resources, layout, templates):
    by_id = {r["id"]: r for r in resources}
    toc, body = [], []
    for section in layout[locale]:
        toc.append(f"- [{section['title']}](#{slug(section['title'])})")
        body += [f"## {section['title']}", ""]
        if section.get("intro"):
            body += [section["intro"], ""]
        for sub in section["subsections"]:
            # An explicit anchor keeps in-page links working where heading ids drop accents.
            if sub.get("anchor"):
                body += [f'<a id="{sub["anchor"]}"></a>', ""]
            if sub.get("title"):
                body += [f"### {sub['title']}", ""]
            if sub.get("intro"):
                body += [sub["intro"], ""]
            for rid in sub["ids"]:
                resource = by_id[rid]
                text = resource[locale]
                body.append(f"- [{text['name']}]({resource['url']}) - {text['description']}")
            if sub["ids"]:
                body.append("")
            if sub.get("after"):
                body += [sub["after"], ""]
    output = templates[locale].replace(TOC_MARKER, "\n".join(toc))
    return output.replace(RESOURCES_MARKER, "\n".join(body).rstrip("\n"))


# --- Command line -----------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail instead of writing stale files")
    args = parser.parse_args(argv)

    resources, layout, templates = load()
    errors = validate(resources, layout, templates)
    if errors:
        print("Validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    stale = []
    for locale, filename in OUTPUTS.items():
        expected = render(locale, resources, layout, templates)
        path = ROOT / filename
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == expected:
            continue
        if args.check:
            stale.append(filename)
        else:
            path.write_text(expected, encoding="utf-8")
            print(f"Wrote {filename}")
    if stale:
        print(
            f"Out of date: {', '.join(stale)}. These files are generated; edit data/ or "
            "templates/ and run `python3 tools/build.py`.",
            file=sys.stderr,
        )
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
