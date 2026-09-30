"""Small, fail-closed release inventory policy shared by refresh and build."""

from __future__ import annotations

import re

SEMVER = re.compile(r"^v\d+\.\d+\.\d+$")


def semver_key(tag: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in tag[1:].split("."))  # type: ignore[return-value]


def projected_releases(row: dict, sourcehut: dict | None, github: dict) -> list[dict]:
    """Return ordered releases, preserving the source of pre-migration tags.

    Inventories contain ``tags`` (raw tag-ref object SHAs), ``main_sha``, and,
    for GitHub, ``published`` annotated releases.  A mixed row additionally
    requires every historical SourceHut tag to have the identical ref object on
    GitHub; this preserves both annotated and lightweight tag identity.
    """
    boundary = row.get("sourcehut_through")
    if not boundary:
        return [
            {"tag": tag, "tag_sha": sha, "provider": row.get("provider", "sourcehut")}
            for tag, sha in sorted(github["tags"].items(), key=lambda item: semver_key(item[0]), reverse=True)
            if tag in github.get("published", github["tags"])
        ]
    if not SEMVER.fullmatch(boundary) or sourcehut is None:
        raise SystemExit(f"{row.get('name', '<unnamed>')}: invalid sourcehut_through inventory")
    cutoff = semver_key(boundary)
    historical = {tag: sha for tag, sha in sourcehut["tags"].items() if semver_key(tag) <= cutoff}
    for tag, sha in historical.items():
        if github["tags"].get(tag) != sha:
            raise SystemExit(f"{row['name']} {tag}: SourceHut and GitHub tag refs do not match")
    releases = [{"tag": tag, "tag_sha": sha, "provider": "sourcehut"} for tag, sha in historical.items()]
    releases += [
        {"tag": tag, "tag_sha": github["tags"][tag], "provider": "github"}
        for tag in github.get("published", [])
        if semver_key(tag) > cutoff and tag in github["tags"]
    ]
    return sorted(releases, key=lambda release: semver_key(release["tag"]), reverse=True)
