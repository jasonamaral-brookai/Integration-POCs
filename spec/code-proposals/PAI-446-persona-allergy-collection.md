# PAI-446: Create PersonaAllergy Collection

**PROPOSAL — not a PR. For Brook Backend team review.**

Linear: https://linear.app/brook-health/issue/PAI-446/clinical-model-create-personaallergy-collection

Blocked on: **Decision 1** (persistence pattern — Constantine). This ticket assumes a new
top-level `persona_allergies` collection (Option A). If Backend chooses to extend
`PatientCarePlans.allergies[]` with coded fields instead, scope changes significantly.

**Clinical safety note:** Allergy data is a patient safety record. Before this ticket
ships, the Backend and DNA teams must define the authoritative source policy: does
EHR-sourced allergy data override care team data, supplement it, or require reconciliation
before display? This is not a blocking question for the collection schema, but it is a
blocking question for the POCAR display path. Flag it in implementation planning.

---

## 1. Proposed Java class

Full source: `spec/data-model-proposals/PersonaAllergy.java`

Key design decisions in the draft:

- **Collection name:** `persona_allergies` (new)
- **FHIR alignment:** `AllergyIntolerance` resource — typed enums for `criticality`,
  `clinicalStatus`, `verificationStatus`, and `allergyType` (not free text)
- **Criticality is a typed enum** — `LOW | HIGH | UNABLE_TO_ASSESS` — not a string.
  This is a clinical safety requirement. The existing care plan `allergies[]` stores
  free text; this collection does not.
- **Dedup index:** `(persona_id, source, source_allergy_id)` unique sparse

Abbreviated field summary:

```
personaId             String      FK → persona._id
providerOfficeId      String?     FK → provider_office._id
source                enum        ATHENA_CCDA | ATHENA_BULK_FHIR | REDOX | MANUAL | OTHER
sourceAllergyId       String?     EHR allergy record ID (dedup key)
clinicalStatus        enum        ACTIVE | INACTIVE | RESOLVED
verificationStatus    enum        UNCONFIRMED | CONFIRMED | REFUTED | ENTERED_IN_ERROR
allergyType           enum?       ALLERGY | INTOLERANCE
categories            List<enum>? FOOD | MEDICATION | ENVIRONMENT | BIOLOGIC
criticality           enum?       LOW | HIGH | UNABLE_TO_ASSESS
allergenName          String      Display name — required (e.g., "Penicillin")
rxNormCode            String?     RxNorm code for medication allergens
snomedCode            String?     SNOMED CT code for non-medication allergens
onsetDate             Instant?    When allergy was first noted
reactions             List?       AllergyReaction (manifestation, manifestationSnomedCode, severity)
ingestedAt            Instant     @CreatedDate
updatedAt             Instant?    @LastModifiedDate
```

MongoDB indexes:
```
persona_status:     { persona_id: 1, clinical_status: 1 }
persona_source_ref: { persona_id: 1, source: 1, source_allergy_id: 1 } (unique, sparse)
```

---

## 2. Repository interface

```java
public interface PersonaAllergyRepository
        extends MongoRepository<PersonaAllergy, String> {

    List<PersonaAllergy> findByPersonaIdAndClinicalStatus(
            String personaId,
            PersonaAllergy.ClinicalStatus clinicalStatus);

    List<PersonaAllergy> findByPersonaId(String personaId);

    Optional<PersonaAllergy> findByPersonaIdAndSourceAndSourceAllergyId(
            String personaId,
            PersonaAllergy.AllergySource source,
            String sourceAllergyId);
}
```

The most common query is `findByPersonaIdAndClinicalStatus(personaId, ACTIVE)` — the
active allergy list for POCAR display.

---

## 3. Notes for the implementing engineer

- `PatientCarePlans.allergies[]` is **not modified by this ticket**. That section
  remains the care team's editable surface. This collection is additive.
- `criticality` must be stored as the typed `Criticality` enum — never as a free-text
  string. If the CCDA allergy entry has no criticality value, store `UNABLE_TO_ASSESS`,
  not null. Null criticality in a patient safety record is operationally ambiguous.
- `rxNormCode` is appropriate for medication allergens (Penicillin, Sulfonamides, etc.).
  `snomedCode` is appropriate for food and environmental allergens. Store whichever is
  present in the CCDA entry; both may be null for older entries.
- `reactions[]` is a list because a single allergen may produce multiple manifestation
  types (e.g., hives and anaphylaxis both recorded for Penicillin).
- `verificationStatus = ENTERED_IN_ERROR` records should not be surfaced in POCAR
  allergy display. Filter them at the query layer, not in the adapter.
- For the clinical safety reconciliation question: do not merge EHR-sourced and care
  team allergies in this ticket. Surface both separately in POCAR and let the DNA team
  define the merge/reconciliation UX as a follow-on.
