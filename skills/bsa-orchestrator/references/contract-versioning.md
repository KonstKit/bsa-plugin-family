# Contract Versioning

## Canonical Version Source
- `A48.CanonPolicyVersion` is the authoritative active contract version.
- Every run must record the active version before Stage 1 starts.

## Version Semantics
- `MAJOR.MINOR.PATCH`.
- `PATCH`: wording clarifications only; no schema/marker/runtime behavior change.
- `MINOR`: backward-compatible additive changes (new optional fields, additive reports, additive checks).
- `MAJOR`: breaking changes (marker rename/removal, required field removal/rename, stage ordering changes, gate logic changes).

## Compatibility Rules
- Producers must not emit artifacts below required version floor for the run profile.
- Consumers must reject artifacts marked with unknown future major version.
- Marker name aliases must be explicitly documented during any migration window.

## Migration Checklist
1. Publish version delta note with impacted artifacts/markers.
2. Update validation scenario manifest with migration checks.
3. Update runtime marker schema and workflow contract together.
4. Add re-entry guidance for in-flight runs crossing versions.
5. Remove compatibility aliases only after migration window closes.
