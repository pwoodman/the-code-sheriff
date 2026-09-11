# Beta testing safely

The safest way to evaluate The Code Sheriff against real open-source projects
is to use disposable, shallow clones and static-only trust settings. Never
run a project's tests, builds, package scripts, or plugins until you have
reviewed that project's code and explicitly accepted trusted execution.

## Disposable OSS checkout

Use a temporary directory outside the project you are developing:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 https://github.com/psf/requests.git "$tmp/requests"
QUALITY_TRUST=untrusted quality --root "$tmp/requests" doctor
QUALITY_TRUST=untrusted quality --root "$tmp/requests" run \
  --skip review,test,compile,coverage,ui
rm -rf "$tmp"
```

The command writes reports only inside the disposable clone. It does not
commit, push, open pull requests, or change the source tree. Keep
`QUALITY_TRUST=untrusted` for repositories you do not own.

## Reusable beta smoke checks

Run these checks against every candidate repository:

```bash
QUALITY_TRUST=untrusted quality --root "$REPO" detect
QUALITY_TRUST=untrusted quality --root "$REPO" security
QUALITY_TRUST=untrusted quality --root "$REPO" audit
QUALITY_TRUST=untrusted quality --root "$REPO" report
```

`test`, `compile`, `coverage`, configured advanced commands, and plugin workers
are execution surfaces. They are blocked in untrusted mode. If an isolated
command is requested, the Sheriff now fails closed unless `bwrap` is installed;
it never silently substitutes ordinary host execution for isolation.

For a project you trust, use a separate disposable clone and review the
generated command list before enabling:

```bash
QUALITY_TRUST=trusted quality --root "$REPO" run --skip review
```

## Suggested OSS corpus

Use repositories with different language/tooling profiles rather than one
project repeatedly:

| Profile | Example |
| --- | --- |
| Python library | `psf/requests` |
| JavaScript application | `vitejs/vite` |
| Rust project | `rust-lang/rustlings` |
| Go project | `prometheus/prometheus` |

Pin a commit when recording a beta result so runs remain reproducible:
`git checkout <commit>` after cloning.

## What to collect from each run

Save the generated `.quality-reports/quality-report.json` and
`.quality-reports/diagnostics.json` files with the repository, commit, and
command used. They include gate status, findings by gate, execution timing,
coverage/duplication metrics, skipped or unavailable tools, AI provider
selection, and evidence identifiers. The Markdown/HTML reports are useful for
human review; redact repository content, tokens, and sensitive paths before
sharing reports outside the beta group.
