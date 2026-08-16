#!/usr/bin/env python3
"""Batch-map supplied mug images to matching storefront products by title."""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "marketing-site"
PUBLIC = SITE / "public"

SUPPLIED = {
    "ask me about weird animals": Path("/Users/kamyartavassoli/Downloads/askmeaboutweiredanimals.jpg"),
    "this might be on the test": Path("/Users/kamyartavassoli/Downloads/Thismightbeonthetest.jpg"),
    "that was unexpectedly educational": Path("/Users/kamyartavassoli/Downloads/thatwasunexpectedly.jpg"),
    "please dont tell the next class": Path("/Users/kamyartavassoli/Downloads/donttellnextclass.jpg"),
    "thats creative not correct but creative": Path("/Users/kamyartavassoli/Downloads/thatscreative.jpg"),
    "variables build character": Path("/Users/kamyartavassoli/Downloads/variablesbuildcharacter.jpg"),
    "i have graded things you cant even imagine": Path("/Users/kamyartavassoli/Downloads/ihavegraded.jpg"),
    "they think i know everything": Path("/Users/kamyartavassoli/Downloads/theythink.jpg"),
    "im silently correcting your grammar": Path("/Users/kamyartavassoli/Downloads/imsilently.jpg"),
}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def source_files():
    for path in SITE.rglob("*"):
        if not path.is_file() or any(p in {"node_modules", ".git", "dist", ".next"} for p in path.parts):
            continue
        if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".json", ".html"}:
            yield path


image_re = re.compile(r"(?:/)?images/mugs/[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|webp)", re.I)


def locate_target(phrase: str):
    candidates = []
    for path in source_files():
        text = path.read_text(errors="ignore")
        normalized = norm(text)
        position = normalized.find(phrase)
        if position < 0:
            continue
        # Normalization changes offsets, so select every nearby product image and
        # rank files containing both the phrase and a unique product image.
        refs = image_re.findall(text)
        for ref in refs:
            asset = PUBLIC / ref.lstrip("/")
            if asset.exists() and "product-" in asset.name:
                # Prefer a block containing both phrase and image reference.
                raw_ref_pos = text.find(ref)
                raw_phrase_words = phrase.split()
                score = sum(1 for word in raw_phrase_words if word in norm(text[max(0, raw_ref_pos-1800):raw_ref_pos+1800]))
                candidates.append((score, asset, path))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], "right-side" in row[1].name), reverse=True)
    best = candidates[0]
    # Refuse ambiguous matches rather than overwriting the wrong product.
    top_assets = {str(row[1]) for row in candidates if row[0] == best[0]}
    return best[1] if len(top_assets) == 1 else None


def main():
    replaced, unmatched = [], []
    for phrase, source in SUPPLIED.items():
        target = locate_target(phrase)
        if not source.exists() or target is None:
            unmatched.append({"phrase": phrase, "reason": "source missing" if not source.exists() else "no unambiguous storefront match"})
            continue
        shutil.copy2(source, target)
        replaced.append({"phrase": phrase, "source": str(source), "target": str(target.relative_to(ROOT))})

    # Inventory all storefront product images so the remaining count is explicit.
    referenced = {}
    for path in source_files():
        text = path.read_text(errors="ignore")
        for ref in image_re.findall(text):
            if "product-" in ref:
                referenced[ref] = True
    replaced_targets = {"/" + item["target"].split("public/", 1)[-1] for item in replaced}
    remaining_assets = sorted(ref for ref in referenced if "/" + ref.lstrip("/") not in replaced_targets)
    report = {
        "replaced_count": len(replaced),
        "replaced": replaced,
        "unmatched_supplied": unmatched,
        "remaining_referenced_image_count": len(remaining_assets),
        "remaining_referenced_images": remaining_assets,
    }
    report_path = ROOT / "marketing-site" / "storefront-image-audit.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
