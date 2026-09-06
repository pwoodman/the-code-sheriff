# Adapter plugins

Plugins register an entry point in the `quality_gates.adapters` group and expose
an `AdapterMetadata` plus a `run(AdapterContext) -> GateResult` implementation.
The API version must equal `ADAPTER_API_VERSION`; incompatible plugins fail
explicitly during discovery.

Plugins must declare input scopes, prerequisites, required permissions, output
schema, and cacheability as well as truthful capabilities and safety class. Use
argument arrays rather than a shell and keep output deterministic. A plugin
failure is reported as an errored result; it must never turn the orchestrator
green. Third-party plugins are not cached automatically and should run only in
the configured isolated worker for untrusted changes.
