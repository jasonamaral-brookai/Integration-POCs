# PAI-444: Create PersonaEncounter Collection

**PROPOSAL — not a PR. For Brook Backend team review.**

Linear: https://linear.app/brook-health/issue/PAI-444/clinical-model-create-personaencounter-collection

Blocked on: **Decision 1** (persistence pattern — Constantine). This ticket cannot begin
until the Backend team confirms that PersonaEncounter is a top-level collection (Option A)
and not an extension of an existing collection. The Java class below assumes Option A.

---

## 1. Proposed Java class

Full source: `spec/data-model-proposals/PersonaEncounter.java`

Key design decisions already made in the draft:

- **Collection name:** `persona_encounters` (new — does not exist in brook-backend)
- **Pattern:** Mirrors `PersonaDiagnosis.java` (PAI-184, merged) — same Lombok annotations,
  same `@Document` + `@CompoundIndex` pattern, same source enum approach
- **Not embedded in Persona** — top-level collection to allow queries by encounter date,
  type, and provider without loading the full Persona document
- **Dedup index:** Compound unique on `(persona_id, source, source_encounter_id)` —
  prevents duplicate ingest when CCDA is fetched more than once for the same patient

Abbreviated field summary:

```
personaId           String      FK → persona._id
providerOfficeId    String?     FK → provider_office._id
source              enum        ATHENA_CCDA | ATHENA_BULK_FHIR | REDOX | MANUAL | OTHER
sourceEncounterId   String?     EHR encounter ID (dedup key)
status              enum        PLANNED | ARRIVED | FINISHED | CANCELLED | ...
encounterClass      String?     AMB | IMP | EMER | HH (free text v1)
encounterType       String?     "Office Visit" | "Annual Wellness Visit" (free text v1)
periodStart         Instant?    Encounter start datetime
periodEnd           Instant?    Encounter end datetime
providers           List?       EncounterProvider (role, name, NPI)
reasonCodes         List?       ReasonCode (ICD-10 system + code + display)
locationName        String?     Clinic display name (snapshot)
dischargeDisposition String?    Inpatient only
ingestedAt          Instant     @CreatedDate
updatedAt           Instant?    @LastModifiedDate
```

MongoDB indexes:
```
persona_encounter_period: { persona_id: 1, period_start: -1 }
persona_source_ref:       { persona_id: 1, source: 1, source_encounter_id: 1 } (unique, sparse)
```

---

## 2. Repository interface

Add to `src/main/java/ai/brook/data/persona/encounter/PersonaEncounterRepository.java`:

```java
public interface PersonaEncounterRepository
        extends MongoRepository<PersonaEncounter, String> {

    List<PersonaEncounter> findByPersonaIdOrderByPeriodStartDesc(String personaId);

    Optional<PersonaEncounter> findByPersonaIdAndSourceAndSourceEncounterId(
            String personaId,
            PersonaEncounter.EncounterSource source,
            String sourceEncounterId);
}
```

The second method is the idempotency check — call before writing to determine
whether a given EHR encounter has already been ingested.

---

## 3. Notes for the implementing engineer

- The `EncounterSource` enum is local to this class (not DiagnosisSource). If Backend
  decides to introduce a single platform-wide source enum, that refactor is a separate ticket.
- `encounterClass` and `encounterType` are free text in v1. Do not block Phase 1a on
  adding SNOMED or CPT coding — that is a future enhancement.
- `reasonCodes[]` maps to the CCDA encounter section's ICD-10 coded entries. If an
  encounter has no coded reason, store an empty list, not null.
- `providerOfficeId` should be populated where the athena `practiceid` maps to a known
  Brook provider office. Leave null if no mapping exists — do not throw.
- The existing `patient_care_plans` collection is not touched by this ticket.
