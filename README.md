# nextflow-container-scan

A small, zero-dependency Python script that clones a public Nextflow git repository
(including submodules), checks out a specific ref, and scans all `.nf` and `.config`
files for `container` directives.

It handles both simple one-liners and multi-line Groovy expressions (ternary,
GString interpolations, etc.), so it works with pipelines that switch between
Docker and Singularity URLs.

## Dependencies

* Python ≥ 3.9
* `git` in `$PATH`

## Usage

```bash
# basic scan (prints JSON to stdout)
python3 nextflow_container_scan.py <repo-url>

# specify a branch / tag / SHA
python3 nextflow_container_scan.py <repo-url> --ref dev

# write results to file
python3 nextflow_container_scan.py <repo-url> -o results.json

# skip HTTP(S) image URLs (e.g. direct SIF/blob URLs)
python3 nextflow_container_scan.py <repo-url> --exclude-http
```

## What is detected

* `container "..."` or `container '...'` inside Nextflow processes (`.nf`)
* `process.container = "..."` in Nextflow config files (`.config`)
* Multi-line conditional expressions:

```nextflow
container "${ workflow.containerEngine in ['singularity', 'apptainer'] ?
    'https://.../image.sif' :
    'docker.io/repo/image:tag' }"
```

Each finding lists the file, line range, full directive text, and extracted
image candidate(s).

## Limitations

The script extracts *quoted string literals* that appear inside container
directives. If an expression relies purely on a variable with no literal
fallback, nothing will be reported for that directive.
