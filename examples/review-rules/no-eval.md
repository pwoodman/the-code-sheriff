---
name: no-eval
paths:
  - "**/*.py"
  - "**/*.js"
  - "**/*.ts"
severity: error
---

Do not introduce `eval`, `new Function`, or equivalent dynamic execution of
untrusted strings. Flag it even when the call looks like a test helper.
