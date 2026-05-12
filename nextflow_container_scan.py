#!/usr/bin/env python3
"""
nextflow-container-scan: Clone a public Nextflow git repository and extract every
container image referenced in process directives.

Handles simple one-liners and multi-line Groovy expressions (ternary, GString
interpolations, etc.).  Zero third-party dependencies.

Usage:
    python nextflow_container_scan.py <repo_url> [--ref REF] [-o results.json]
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def clone_repo(url: str, ref: str, dest: Path, verbose: bool = False) -> None:
    """Clone a repo (with submodules) and checkout *ref*."""
    kwargs = {} if verbose else {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    subprocess.run(["git", "clone", "--recursive", url, str(dest)], check=True, **kwargs)
    if ref != "HEAD":
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth=1", "origin", ref],
            check=False,
            **kwargs
        )
        subprocess.run(
            ["git", "-C", str(dest), "checkout", ref],
            check=True,
            **kwargs
        )
    subprocess.run(
        ["git", "-C", str(dest), "submodule", "update", "--init", "--recursive"],
        check=True,
        **kwargs
    )


def _quote_states(text: str):
    """Return whether we end inside a single- or double-quoted string."""
    in_single = False
    in_double = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
    return in_single, in_double


def capture_container_expr(lines: list[str], start: int) -> tuple[str, int]:
    """Given lines and the index of a ``container ...`` line, return the full
    expression string and the index of the last line consumed."""
    raw = lines[start]
    m = re.match(r"^(\s*)container\s+(.*)", raw, re.IGNORECASE)
    if not m:
        return raw.strip(), start
    expr = m.group(2)
    buf = expr
    idx = start
    in_single, in_double = _quote_states(buf)
    while (in_single or in_double) and idx + 1 < len(lines):
        idx += 1
        buf += "\n" + lines[idx]
        in_single, in_double = _quote_states(buf)
    return buf, idx


def extract_candidates(expr: str) -> list[str]:
    """Extract container image candidates from a container expression."""
    candidates: list[str] = []
    stripped = expr.strip()

    # 1. Simple single-quoted or double-quoted literal (no interpolation)
    #    The [^'\n] / [^"\n] guards prevent a multiline GString from being
    #    swallowed as one giant literal.
    m = re.match(r"^'([^'\n]*)'$", stripped)
    if m:
        return [m.group(1)]
    m = re.match(r'^"([^"\n]*)"$', stripped)
    if m:
        return [m.group(1)]

    # 2. Complex expressions – look for string literals that appear as branch
    #    values in ternary / elvis operators. These are the *actual* images in a
    #    conditional directive like:
    #        "${ cond ? 'img1' : 'img2' }"
    #    or   params.singularity ? 'img1' : 'img2'
    #    or   params.container ?: 'default_img'
    patterns = [
        r"\?\s*'([^']+)'",      # ? 'img'
        r":\s*'([^']+)'",       # : 'img'
        r"\?:\s*'([^']+)'",     # ?: 'img'  (elvis)
        r'\?\s*"([^"]+)"',      # ? "img"
        r':\s*"([^"]+)"',       # : "img"
        r'\?:\s*"([^"]+)"',     # ?: "img"
    ]
    for pat in patterns:
        for m in re.finditer(pat, expr):
            candidates.append(m.group(1))

    if candidates:
        return _filter_candidates(candidates)

    # 3. Fallback: grab any quoted literal that looks like an image.
    for m in re.finditer(r"'([^']+)'", expr):
        candidates.append(m.group(1))
    for m in re.finditer(r'"([^"]+)"', expr):
        candidates.append(m.group(1))
    return _filter_candidates(candidates)


def _filter_candidates(raw: list[str]) -> list[str]:
    """Remove obvious false-positives (engine names, empty placeholders)."""
    skip = {"docker", "singularity", "apptainer", "podman", "shifter", "charliecloud"}
    out = []
    for s in raw:
        if s.strip().startswith("$"):
            continue  # variable interpolation, not a literal
        if s.strip().lower() in skip:
            continue
        out.append(s)
    return out


def scan_nf_file(path: Path, root: Path) -> list[dict]:
    """Scan a single .nf file for process-level container directives."""
    results = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        if not re.match(r"^\s*container\s+\S", line, re.IGNORECASE):
            i += 1
            continue
        # skip false positives like workflow.containerEngine
        token = line.strip().split()[0].lower()
        if token != "container":
            i += 1
            continue

        expr, end_idx = capture_container_expr(lines, i)
        images = extract_candidates(expr)

        if images:
            results.append(
                {
                    "file": str(path.relative_to(root)),
                    "line_start": i + 1,
                    "line_end": end_idx + 1,
                    "directive": expr.strip(),
                    "images": images,
                }
            )
        i = end_idx + 1
    return results


def scan_config_file(path: Path, root: Path) -> list[dict]:
    """Scan Nextflow config files for ``process.container = ...`` assignments."""
    results = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    for i, line in enumerate(lines):
        m = re.match(r"^\s*process\.container\s*=\s*(.+)$", line)
        if not m:
            continue
        expr = m.group(1)
        images = extract_candidates(expr)
        if images:
            results.append(
                {
                    "file": str(path.relative_to(root)),
                    "line_start": i + 1,
                    "line_end": i + 1,
                    "directive": expr.strip(),
                    "images": images,
                }
            )
    return results


def find_all_containers(root: Path, exclude_http: bool = False) -> list[dict]:
    """Walk the repo and collect every container reference."""
    findings = []
    for nf in root.rglob("*.nf"):
        findings.extend(scan_nf_file(nf, root))
    for cfg in root.rglob("*.config"):
        findings.extend(scan_config_file(cfg, root))
    if exclude_http:
        for f in findings:
            f["images"] = [img for img in f["images"] if not img.startswith(("http://", "https://"))]
        findings = [f for f in findings if f["images"]]
    findings.sort(key=lambda d: (d["file"], d["line_start"]))
    return findings


def _unique_images(findings: list[dict]) -> list[str]:
    """Return a deduplicated, sorted list of every image name found."""
    seen = set()
    for f in findings:
        for img in f["images"]:
            seen.add(img)
    return sorted(seen)


def _add_registry(image: str, registry: str) -> str:
    """Prepend *registry* to images that do not already carry one.

    Docker determines whether the first slash-delimited component is a registry
    if it contains a dot (.) or a colon (:) or equals ``localhost``.
    """
    if "/" not in image:
        return f"{registry}/{image}"
    first = image.split("/", 1)[0]
    if "." in first or ":" in first or first == "localhost":
        return image
    return f"{registry}/{image}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan a public Nextflow git repository for container directives."
    )
    parser.add_argument("repo", help="Git remote URL (public repo)")
    parser.add_argument(
        "--ref", default="HEAD", help="Git ref to checkout (branch/tag/sha). Default: HEAD"
    )
    parser.add_argument("-o", "--output", help="Write results to this file")
    parser.add_argument(
        "--full-json", action="store_true",
        help="Output full JSON with file locations and directives (default: flat unique image list)"
    )
    parser.add_argument(
        "--include-http", action="store_true",
        help="Include image references that start with 'http://' or 'https://' (excluded by default)"
    )
    parser.add_argument(
        "--registry", default="quay.io",
        help="Default registry to prepend to unqualified image names (default: quay.io). Pass '' to disable."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print progress messages to stderr (default: quiet)"
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "repo"
        if args.verbose:
            print(f"Cloning {args.repo} @ {args.ref} …", file=sys.stderr)
        clone_repo(args.repo, args.ref, dest, verbose=args.verbose)
        if args.verbose:
            print("Scanning for container directives …", file=sys.stderr)
        results = find_all_containers(dest, exclude_http=not args.include_http)

    registry = args.registry.strip()
    if registry:
        for f in results:
            f["images"] = [_add_registry(img, registry) for img in f["images"]]

    if args.output and not args.full_json:
        unique = _unique_images(results)
        Path(args.output).write_text("\n".join(unique) + ("\n" if unique else ""))
        if args.verbose:
            print(f"Wrote {len(unique)} unique image(s) to {args.output}", file=sys.stderr)
        return

    if not args.full_json:
        # Flat list to stdout
        unique = _unique_images(results)
        if unique:
            print("\n".join(unique))
        return

    payload = {
        "repo": args.repo,
        "ref": args.ref,
        "total_findings": len(results),
        "containers": results,
    }
    json_text = json.dumps(payload, indent=2)

    if args.output:
        Path(args.output).write_text(json_text)
        print(f"Wrote {len(results)} finding(s) to {args.output}")
    else:
        print(json_text)


if __name__ == "__main__":
    main()
