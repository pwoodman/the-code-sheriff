# Third-party notices

The Code Sheriff itself is MIT licensed. It interoperates with third-party tools but
does not incorporate their binaries. Tool names, versions, capabilities, and
SPDX-style license identifiers are listed in `configs/tool-manifest.json`.

The SBOM workflow generates an SPDX JSON inventory and a license inventory on
each main-branch build and release. Users installing optional tools must comply
with those tools' licenses; `VARIES`, `UNKNOWN`, and proprietary entries require
independent review.
