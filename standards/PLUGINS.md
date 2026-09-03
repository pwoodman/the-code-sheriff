# Adapter plugins

Plugins register an entry point in the `quality_gates.adapters` group and expose
an `AdapterMetadata` plus a `run(AdapterContext) -> GateResult` implementation.
The API version must equal `ADAPTER_API_VERSION`; incompatible plugins fail
explicitly during discovery.

Plugins execute in the quality process and are not sandboxed. Install only
trusted plugins. Declare truthful capabilities and safety class, use argument
arrays rather than a shell, keep output deterministic, and use the standard
statuses: pass, fail, warning, skip, not-applicable, unsupported, or tool-error.
Third-party plugins are not cached automatically and may perform network calls.
