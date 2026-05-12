# nextflow-container-scan

A small, zero-dependency Python script that clones a public Nextflow git repository
(including submodules), checks out a specific ref, and scans all `.nf` and `.config`
files for `container` directives.

It handles both simple one-liners and multi-line Groovy expressions (ternary,
GString interpolations, etc.), so it works with pipelines that switch between
Docker and Singularity images.

## Dependencies

* Python ≥ 3.9
* `git` in `$PATH`

## Usage

```bash
# default: unique image names, one per line (skips http:// / https:// URLs)
python3 nextflow_container_scan.py <repo-url>

# include Singularity / SIF URLs that start with https://
python3 nextflow_container_scan.py <repo-url> --include-http

# full JSON output with file locations and directive text
python3 nextflow_container_scan.py <repo-url> --full-json

# specify a branch / tag / SHA
python3 nextflow_container_scan.py <repo-url> --ref dev

# write results to a file
python3 nextflow_container_scan.py <repo-url> -o images.txt
python3 nextflow_container_scan.py <repo-url> --full-json -o results.json
```

## What is detected

* `container "..."` or `container '...'` inside Nextflow processes (`.nf`)
* `process.container = "..."` in Nextflow config files (`.config`)
* Multi-line conditional expressions, e.g.:

```nextflow
container "${ workflow.containerEngine in ['singularity', 'apptainer'] ?
    'https://.../image.sif' :
    'docker.io/repo/image:tag' }"
```

By default, any reference starting with `http://` or `https://` is excluded.
Use `--include-http` to keep them.

## Limitations

The script extracts *quoted string literals* that appear inside container
directives. If an expression relies purely on a variable with no literal
fallback, nothing will be reported for that directive.
