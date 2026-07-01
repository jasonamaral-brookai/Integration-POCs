# PAI-443: Add ATHENA_CCDA and ATHENA_BULK_FHIR to DiagnosisSource

**PROPOSAL — not a PR. For Brook Backend team review.**

Linear: https://linear.app/brook-health/issue/PAI-443/clinical-model-add-athena-ccda-and-athena-bulk-fhir-to-diagnosissource

`DiagnosisSource.java` exists in brook-backend with five values: `PAP`, `REDOX`, `MANUAL`,
`MIGRATION`, `OTHER`. Two values required for CCDA and Bulk FHIR ingest paths are missing.
This is a prerequisite for the diagnosis adapter in PAI-435 — no integration code can write
to `persona.diagnoses[]` with a valid source until these values exist.

Estimated effort: 1-2 hours including test updates.

---

## 1. Current state (for reference)

Path: `src/main/java/ai/brook/model/DiagnosisSource.java` (confirm exact path before applying)

```java
public enum DiagnosisSource {
    PAP,
    REDOX,
    MANUAL,
    MIGRATION,
    OTHER
}
```

---

## 2. Proposed change

```java
public enum DiagnosisSource {
    PAP,
    REDOX,
    MANUAL,
    MIGRATION,
    OTHER,
    ATHENA_CCDA,       // EHR-sourced diagnosis via C-CDA problem list section (LOINC 11450-4)
    ATHENA_BULK_FHIR   // EHR-sourced diagnosis via athena Bulk FHIR $export (Condition resource)
}
```

---

## 3. Test update

Any existing test that enumerates all `DiagnosisSource` values or asserts on `values().length`
must be updated to include the two new values.

Example — if a test like this exists:

```java
@Test
void diagnosisSource_hasExpectedValues() {
    assertThat(DiagnosisSource.values()).containsExactlyInAnyOrder(
            DiagnosisSource.PAP,
            DiagnosisSource.REDOX,
            DiagnosisSource.MANUAL,
            DiagnosisSource.MIGRATION,
            DiagnosisSource.OTHER
    );
}
```

Update to:

```java
@Test
void diagnosisSource_hasExpectedValues() {
    assertThat(DiagnosisSource.values()).containsExactlyInAnyOrder(
            DiagnosisSource.PAP,
            DiagnosisSource.REDOX,
            DiagnosisSource.MANUAL,
            DiagnosisSource.MIGRATION,
            DiagnosisSource.OTHER,
            DiagnosisSource.ATHENA_CCDA,
            DiagnosisSource.ATHENA_BULK_FHIR
    );
}
```

---

## 4. Notes for the implementing engineer

- No existing `DiagnosisSource.PAP`, `REDOX`, `MANUAL`, `MIGRATION`, or `OTHER` usages
  are changed by this ticket. Enum extension is backwards compatible.
- `ATHENA_CCDA` is used by the CCDA diagnosis adapter (PAI-435) when writing parsed
  problem list entries from CCDA section LOINC 11450-4 to `persona.diagnoses[]`.
- `ATHENA_BULK_FHIR` is used by the Bulk FHIR ingest path (PAI-421) when writing
  Condition resources from the `$export` NDJSON payload to `persona.diagnoses[]`.
- If `DiagnosisSource` is serialized to MongoDB as a string (common with Spring Data),
  confirm no existing documents use a value that would conflict with the new names.
  New values are additive; existing stored strings are unaffected.
- Deploy to the integration environment before PAI-435 CCDA adapter integration tests run.
  The diagnosis adapter cannot be tested end-to-end until this enum value is available
  in the target environment.
- If `DiagnosisSource` is referenced in any dbt models or ETL-service queries
  (e.g., `WHERE diagnosis_source = 'REDOX'`), confirm those queries are not broken
  by the addition of new values. Addition of new enum values should not affect
  existing filter predicates.
