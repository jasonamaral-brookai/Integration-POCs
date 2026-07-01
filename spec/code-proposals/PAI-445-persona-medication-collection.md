# PAI-445: Create PersonaMedication Collection

**PROPOSAL — not a PR. For Brook Backend team review.**

Linear: https://linear.app/brook-health/issue/PAI-445/clinical-model-create-personamedication-collection

Blocked on: **Decision 1** (persistence pattern — Constantine). This ticket assumes
a new top-level `persona_medications` collection (Option A). If Backend chooses to
extend `PatientCarePlans.currentMedications[]` instead, the scope of this ticket changes
significantly — confirm before starting.

**Also note:** The existing `patient_care_plans.current_medications[]` section is the
care team's editable medication list. This collection is parallel to it, not a replacement.
Backend and DNA teams must decide whether both surfaces show in POCAR and whether
de-duplication is required (see data-model-gaps.md, Decision 2).

---

## 1. Proposed Java class

Full source: `spec/data-model-proposals/PersonaMedication.java`

Key design decisions in the draft:

- **Collection name:** `persona_medications` (new)
- **FHIR alignment:** `MedicationStatement` (not `MedicationRequest`) — CCDA medication
  section does not always carry prescriber/intent metadata required for MedicationRequest
- **RxNorm is nullable** — older CCDA entries may provide drug name only; do not reject
  records without an RxNorm code
- **Dedup index:** `(persona_id, source, source_medication_id)` unique sparse

Abbreviated field summary:

```
personaId           String      FK → persona._id
providerOfficeId    String?     FK → provider_office._id
source              enum        ATHENA_CCDA | ATHENA_BULK_FHIR | REDOX | MANUAL | OTHER
sourceMedicationId  String?     EHR medication/prescription ID (dedup key)
medicationName      String      Display name — required (e.g., "Metformin 500mg")
rxNormCode          String?     RxNorm concept ID (e.g., "860975")
ndcCode             String?     National Drug Code
status              enum        ACTIVE | INACTIVE | STOPPED | ON_HOLD | UNKNOWN | ...
effectiveStart      Instant?    When medication was started
effectiveEnd        Instant?    When stopped (null = currently active)
dosageText          String?     Full SIG text from CCDA
doseValue           Double?     Numeric dose quantity
doseUnit            String?     Unit (e.g., "mg", "mL")
route               String?     "oral" | "subcutaneous" | ...
frequencyText       String?     "twice daily" | "every 8 hours"
prescriberName      String?     Ordering provider display name (snapshot)
prescriberNpi       String?     Provider NPI
ingestedAt          Instant     @CreatedDate
updatedAt           Instant?    @LastModifiedDate
```

MongoDB indexes:
```
persona_status_effective: { persona_id: 1, status: 1, effective_start: -1 }
persona_source_ref:       { persona_id: 1, source: 1, source_medication_id: 1 } (unique, sparse)
```

---

## 2. Repository interface

```java
public interface PersonaMedicationRepository
        extends MongoRepository<PersonaMedication, String> {

    List<PersonaMedication> findByPersonaIdAndStatusOrderByEffectiveStartDesc(
            String personaId,
            PersonaMedication.MedicationStatus status);

    List<PersonaMedication> findByPersonaIdOrderByEffectiveStartDesc(String personaId);

    Optional<PersonaMedication> findByPersonaIdAndSourceAndSourceMedicationId(
            String personaId,
            PersonaMedication.MedicationSource source,
            String sourceMedicationId);
}
```

---

## 3. Notes for the implementing engineer

- `PatientCarePlans.current_medications[]` is **not modified by this ticket**. The care
  plan section remains the care team's editable surface. This collection is additive.
- `rxNormCode` is the preferred dedup key within a patient's medication list. If two
  CCDA fetches return the same medication with different `sourceMedicationId` values
  (e.g., refills), dedup logic should be in the adapter layer (PAI-435), not here.
- `dosageText` is the full SIG string from CCDA. Parse into `doseValue`, `doseUnit`,
  `route`, and `frequencyText` where possible; fall back to `dosageText` only when
  structured parsing fails.
- `effectiveEnd = null` means the medication is currently active. Queries for the
  current medication list should filter on `status = ACTIVE` or `effectiveEnd = null`.
- Do not store `prescriberName` as a FK — it is a snapshot from the EHR at ingest time.
