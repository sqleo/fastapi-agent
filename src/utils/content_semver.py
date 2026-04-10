"""文件内容语义版本：解析 PATCH 进位、重新上传 MAJOR 递增."""

from __future__ import annotations


def format_semver(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def parse_semver_tuple(s: str) -> tuple[int, int, int] | None:
    parts = (s or "").strip().split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def compare_semver(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    if a > b:
        return 1
    if a < b:
        return -1
    return 0


def bump_patch_after_parse(major: int, minor: int, patch: int) -> tuple[int, int, int]:
    """每次解析成功：PATCH +1；0.0.9→0.0.10；0.0.10→0.1.0（PATCH 上限为 10 后进 MINOR）。"""
    if patch < 9:
        return major, minor, patch + 1
    if patch == 9:
        return major, minor, 10
    # patch == 10
    return major, minor + 1, 0


def bump_major_after_reupload(major: int, minor: int, patch: int) -> tuple[int, int, int]:
    """重新上传同一 file_asset：MAJOR+1，MINOR/PATCH 归零。"""
    return major + 1, 0, 0
