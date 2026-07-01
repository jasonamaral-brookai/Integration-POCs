# PAI-447: EHR Vital Signs Persistence

**PROPOSAL — not a PR. For Brook Backend team review.**

Linear: https://linear.app/brook-health/issue/PAI-447/clinical-model-ehr-vital-signs-persistence

Blocked on: **Decision 4** (PersonaVital vs. ActivitySource extension — Constantine).
This ticket has two implementation paths. **Do not start until Decision 4 is resolved.**
Both paths are documented below.

---

## Decision 4 summary (for context)

| | Option A — New collection | Option B — Extend activity |
|---|---|---|
| What ships | `PersonaVital` @Document class + new `persona_vitals` collection | Add `ATHENA_CCDA` and `ATHENA_BULK_FHIR` to `ActivitySource.SourceType` enum |
| Risk | New display path required in POCAR | dbt billing models may count EHR vitals as RPM device readings |
| Effort | L | M |
| dbt impact | None (separate collection) | Must audit all billing aggregations that touch `activity` |

The class below is drafted for **Option A**. If Option B is chosen, skip to Section 3.

---

## Option A: New PersonaVital collection

### 1. Proposed Java class

Full source: `spec/data-model-proposals/PersonaVital.java`

Key design decisions in the draft:

- **Collection name:** `persona_vitals` (new)
- **FHIR alignment:** `Observation` resource with `category = vital-signs`
- **Supports panels:** Blood pressure is stored as a panel via `components[]`
  (systolic LOINC 8480-6 + diastolic LOINC 8462-4) — not as two separate records
- **Distinct from `activity`:** This collection stores EHR-sourced historical vitals
  (clinic-recorded). The `activity` collection stores device-sourced RPM readings for
  billing. These must not be mixed.
- **Dedup index:** `(persona_id, source, source_observation_id)` unique sparse

Abbreviated field summary:

```
personaId             String      FK → persona._id
providerOfficeId      String?     FK → provider_office._id
source                enum        ATHENA_CCDA | ATHENA_BULK_FHIR | REDOX | MANUAL | OTHER
sourceObservationId   String?     EHR observation ID (dedup key)
loincCode             String?     LOINC code (e.g., "8480-6", "29463-7")
displayName           String      Human-readable name — required
status                enum        FINAL | AMENDED | PRELIMINARY | CANCELLED | ...
effectiveAt           Instant     When the vital was recorded (office visit datetime)
value                 Double?     Numeric value for single-component vitals
valueUnit             String?     UCUM unit (e.g., "mm[Hg]", "kg", "[lb_av]", "%")
components            List?       VitalComponent (for BP panel: systolic + diastolic)
interpretation        String?     HL7 code: "H" = High, "L" = Low, "N" = Normal
performerName         String?     Provider/nurse who recorded (snapshot)
encounterId           String?     FK → persona_encounters._id (if linked to an encounter)
ingestedAt            Instant     @CreatedDate
updatedAt             Instant?    @LastModifiedDate
```

Common LOINC codes for Brook's population:

| Vital | LOINC |
|-------|-------|
| Systolic BP | 8480-6 |
| Diastolic BP | 8462-4 |
| BP panel | 55284-4 |
| Body weight | 29463-7 |
| BMI | 39156-5 |
| Heart rate | 8867-4 |
| Body temp | 8310-5 |
| O2 sat | 2708-6 |
| Fasting glucose | 1558-6 |

MongoDB indexes:
```
persona_loinc_effective: { persona_id: 1, loinc_code: 1, effective_at: -1 }
persona_effective:       { persona_id: 1, effective_at: -1 }
persona_source_ref:      { persona_id: 1, source: 1, source_observation_id: 1 } (unique, sparse)
```

### 2. Repository interface

```java
public interface PersonaVitalRepository
        extends MongoRepository<PersonaVital, String> {

    List<PersonaVital> findByPersonaIdOrderByEffectiveAtDesc(String personaId);

    List<PersonaVital> findByPersonaIdAndLoincCodeOrderByEffectiveAtDesc(
            String personaId, String loincCode);

    Optional<PersonaVital> findByPersonaIdAndSourceAndSourceObservationId(
            String personaId,
            PersonaVital.VitalSource source,
            String sourceObservationId);
}
```

---

## Option B: Extend ActivitySource.SourceType

If Decision 4 resolves to Option B, this ticket's scope is:

**File:** `src/main/java/ai/brook/data/activity/ActivitySource.java`

Add to `SourceType` enum:

```java
ATHENA_CCDA,       // EHR-sourced vital sign from CCDA vital signs section (Phase 1a)
ATHENA_BULK_FHIR   // EHR-sourced vital sign from Bulk FHIR Observation resource (Phase 3)
```

**Required follow-on work (must happen before Phase 1a ships):**

1. Audit all dbt models that aggregate or filter on the `activity` collection.
   Confirm that any model computing RPM billing minutes or device reading counts
   explicitly excludes `source_type IN ('ATHENA_CCDA', 'ATHENA_BULK_FHIR')`.

2. Add a test fixture that inserts an `activity` record with `SourceType.ATHENA_CCDA`
   and asserts it does not appear in the RPM billing query result set.

3. Confirm with the data team that `monitoring_time_raw` and related dbt models
   filter by source type, not by collection alone.

**Do not ship Option B without completing the dbt audit.** If the audit finds that
billing models do not filter by source type, Option A is the safer choice regardless
of the additional build cost.

---

## Notes for the implementing engineer (both options)

- EHR-sourced historical vitals and device-sourced RPM readings are clinically and
  operationally distinct. Historical vitals from a clinic visit in 2023 are not RPM
  monitoring data. Mixing them causes incorrect billing calculations and incorrect
  POCAR trend displays.
- `encounterId` links a vital to the encounter during which it was recorded. This is
  optional — if the CCDA vital signs section entry does not reference an encounter,
  leave it null. Do not block ingest on missing encounter linkage.
- Blood pressure must be stored as a panel with `components[]`. Do not store systolic
  and diastolic as two separate `PersonaVital` records — they are parts of one
  observation. The panel LOINC code is 55284-4.
