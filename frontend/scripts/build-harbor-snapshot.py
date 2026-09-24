#!/usr/bin/env python3
"""Build a bounded, offline harbor snapshot from the official OSM map API."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


HARBORS = {
    "busan": (
        (129.035, 35.105, 129.055, 35.120),
        "busan-north-port.json",
        "https://api.openstreetmap.org/api/0.6/map?bbox=129.035,35.105,129.055,35.120",
    ),
    "singapore": (
        (103.827, 1.252, 103.851, 1.274),
        "singapore-harbor.json",
        "https://api.openstreetmap.org/api/0.6/map?bbox=103.827,1.252,103.851,1.274",
    ),
}
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "public/harbor"
HEIGHT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m|meter|metres|meters|ft|feet|')?\s*$", re.I)
LEVEL_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")


def inside(point: tuple[float, float], bbox: tuple[float, float, float, float]) -> bool:
    lon, lat = point
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def parse_height(tags: dict[str, str], way_id: int) -> tuple[float, str]:
    raw_height = tags.get("height", "").replace(",", ".")
    match = HEIGHT_RE.fullmatch(raw_height)
    if match:
        value = float(match.group(1))
        if match.group(2) and match.group(2).lower() in {"ft", "feet", "'"}:
            value *= 0.3048
        if 1 <= value <= 1000:
            return round(value, 2), "height"
    levels = LEVEL_RE.fullmatch(tags.get("building:levels", "").replace(",", "."))
    if levels:
        value = float(levels.group(1)) * 3.0
        if 1 <= value <= 1000:
            return round(value, 2), "building:levels:estimated_3m_per_level"
    # A stable visual placeholder, never presented as an observed building height.
    return float((2 + way_id % 5) * 3), "fallback:estimated"


def clip_segment(
    a: tuple[float, float], b: tuple[float, float], bbox: tuple[float, float, float, float]
) -> list[list[float]] | None:
    dx, dy = b[0] - a[0], b[1] - a[1]
    p = (-dx, dx, -dy, dy)
    q = (a[0] - bbox[0], bbox[2] - a[0], a[1] - bbox[1], bbox[3] - a[1])
    lo, hi = 0.0, 1.0
    for pi, qi in zip(p, q, strict=True):
        if pi == 0:
            if qi < 0:
                return None
            continue
        t = qi / pi
        if pi < 0:
            lo = max(lo, t)
        else:
            hi = min(hi, t)
        if lo > hi:
            return None
    if lo == hi:
        return None
    return [
        [round(a[0] + lo * dx, 7), round(a[1] + lo * dy, 7)],
        [round(a[0] + hi * dx, 7), round(a[1] + hi * dy, 7)],
    ]


def clip_line(
    points: list[tuple[float, float]], bbox: tuple[float, float, float, float]
) -> list[list[list[float]]]:
    runs: list[list[list[float]]] = []
    for a, b in zip(points, points[1:]):
        clipped = clip_segment(a, b, bbox)
        if not clipped:
            continue
        if runs and runs[-1][-1] == clipped[0]:
            if runs[-1][-1] != clipped[1]:
                runs[-1].append(clipped[1])
        elif clipped[0] != clipped[1]:
            runs.append(clipped)
    return runs


def read_osm(
    source: bytes, bbox: tuple[float, float, float, float]
) -> tuple[dict[int, tuple[float, float]], list[ET.Element]]:
    root = ET.fromstring(source)
    if root.tag != "osm" or root.get("version") != "0.6":
        raise ValueError("Expected an OSM API 0.6 XML response")
    bounds = root.find("bounds")
    if bounds is None:
        raise ValueError("OSM response has no bounds element")
    actual = tuple(float(bounds.attrib[key]) for key in ("minlon", "minlat", "maxlon", "maxlat"))
    if any(abs(a - b) > 1e-7 for a, b in zip(actual, bbox, strict=True)):
        raise ValueError(f"Unexpected OSM response bounds: {actual}")
    nodes: dict[int, tuple[float, float]] = {}
    for node in root.findall("node"):
        point = (float(node.attrib["lon"]), float(node.attrib["lat"]))
        if not all(map(math.isfinite, point)) or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
            raise ValueError(f"Invalid OSM coordinate on node {node.attrib['id']}")
        nodes[int(node.attrib["id"])] = point
    return nodes, root.findall("way")


def build(
    source: bytes,
    retrieved_at: str,
    bbox: tuple[float, float, float, float],
    source_url: str,
) -> dict:
    try:
        timestamp = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("retrievedAt must be an ISO 8601 timestamp") from error
    if timestamp.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("retrievedAt must use UTC")
    nodes, ways = read_osm(source, bbox)
    buildings: list[dict] = []
    roads: list[dict] = []
    coastline: list[dict] = []
    for way in ways:
        way_id = int(way.attrib["id"])
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        refs = [int(nd.attrib["ref"]) for nd in way.findall("nd")]
        if not ("building" in tags or "highway" in tags or tags.get("natural") == "coastline"):
            continue
        if any(ref not in nodes for ref in refs):
            raise ValueError(f"OSM way {way_id} has an unresolved node reference")
        points = [nodes[ref] for ref in refs]
        if tags.get("building") not in (None, "no") and tags.get("area") != "no":
            if len(refs) >= 4 and refs[0] == refs[-1] and all(inside(point, bbox) for point in points):
                coordinates = [[round(x, 7), round(y, 7)] for x, y in points]
                area = sum(
                    coordinates[i][0] * coordinates[i + 1][1]
                    - coordinates[i + 1][0] * coordinates[i][1]
                    for i in range(len(coordinates) - 1)
                )
                if abs(area) > 1e-12 and len(set(map(tuple, coordinates[:-1]))) >= 3:
                    height, height_source = parse_height(tags, way_id)
                    buildings.append({
                        "id": f"way/{way_id}",
                        "coordinates": coordinates,
                        "heightMeters": height,
                        "heightSource": height_source,
                    })
        if "highway" in tags:
            for index, coordinates in enumerate(clip_line(points, bbox), start=1):
                roads.append({"id": f"way/{way_id}:{index}", "coordinates": coordinates})
        if tags.get("natural") == "coastline":
            for index, coordinates in enumerate(clip_line(points, bbox), start=1):
                coastline.append({"id": f"way/{way_id}:{index}", "coordinates": coordinates})
    if not buildings or not roads or not coastline:
        raise ValueError("Snapshot must contain buildings, roads, and coastline")
    return {
        "metadata": {
            "source": source_url,
            "license": "Open Database License (ODbL) 1.0",
            "bbox": list(bbox),
            "retrievedAt": retrieved_at,
            "sourceSha256": hashlib.sha256(source).hexdigest(),
            "attribution": "© OpenStreetMap contributors",
        },
        "buildings": buildings,
        "roads": roads,
        "coastline": coastline,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor", choices=HARBORS, default="busan")
    parser.add_argument("--input", type=Path, help="Local OSM XML to regenerate a fixed snapshot")
    parser.add_argument("--output", type=Path, help="Destination JSON path")
    parser.add_argument("--retrieved-at", help="UTC ISO 8601 source retrieval time (required with --input)")
    args = parser.parse_args()
    bbox, filename, source_url = HARBORS[args.harbor]
    output = args.output or DEFAULT_DIRECTORY / filename
    if args.input:
        if not args.retrieved_at:
            parser.error("--retrieved-at is required with --input")
        source = args.input.read_bytes()
    else:
        if args.retrieved_at:
            parser.error("--retrieved-at may only be used with --input")
        request = urllib.request.Request(source_url, headers={"User-Agent": "BlueLog harbor visualization experiment"})
        with urllib.request.urlopen(request, timeout=45) as response:
            source = response.read()
        args.retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = build(source, args.retrieved_at, bbox, source_url)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        f"{output}: {len(result['buildings'])} buildings, "
        f"{len(result['roads'])} road segments, {len(result['coastline'])} coastline segments"
    )


if __name__ == "__main__":
    main()
