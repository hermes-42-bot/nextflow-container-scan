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
# default: unique image names, one per line (quiet mode)
python3 nextflow_container_scan.py <repo-url>

# show progress on stderr
python3 nextflow_container_scan.py <repo-url> --verbose

# include Singularity / SIF URLs that start with https://
python3 nextflow_container_scan.py <repo-url> --include-http

# full JSON output with file locations and directive text
python3 nextflow_container_scan.py <repo-url> --full-json

# use a different default registry for unqualified image names
python3 nextflow_container_scan.py <repo-url> --registry my-registry.io

# disable registry prefixing entirely
python3 nextflow_container_scan.py <repo-url> --registry ""

# specify a branch / tag / SHA
python3 nextflow_container_scan.py <repo-url> --ref dev

# write results to a file
python3 nextflow_container_scan.py <repo-url> -o images.txt
python3 nextflow_container_scan.py <repo-url> --full-json -o results.json
```

## Default registry normalization

By default, unqualified image names (e.g. `ubuntu:latest`, `library/busybox`)
are prefixed with `quay.io/`. This helps compare images across pipelines that
mix qualified (`docker.io/...`) and unqualified references.

Docker's algorithm is used to detect whether an image already carries a
registry prefix:

* If the first slash-delimited component **contains a dot (.)** → treated as a
  registry, e.g. `docker.io/library/ubuntu` → no change.
* If it **contains a colon (:)** → treated as a registry, e.g.
  `localhost:5000/image` → no change.
* If it **equals `localhost`** → treated as a registry, e.g. `localhost/image`
  → no change.
* Otherwise, the image is unqualified and the default registry is prepended.

Override the default with `--registry <host>` or disable it entirely with
`--registry ""`.

## What is detected

* `container "..."` or `container '...'` inside Nextflow processes (`.nf`)
* `process.container = "..."` in Nextflow config files (`.config`)
* Multi-line conditional expressions, e.g.:

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
