# Editor diagnostics

After `quality run`, `.quality-reports/diagnostics.json` lists path:line
findings. Point a problem matcher at it:

```json
{
  "problemMatcher": [
    {
      "owner": "quality-gates",
      "fileLocation": ["relative", "${workspaceFolder}"],
      "pattern": {
        "regexp": "\"path\": \"([^\"]+)\".*\"line\": ([0-9]+).*\"severity\": \"(\\w+)\".*\"message\": \"([^\"]+)\"",
        "file": 1,
        "line": 2,
        "severity": 3,
        "message": 4
      }
    }
  ]
}
```

Or open `.quality-reports/quality-report.html` and filter by gate / file.
No marketplace extension is required.
