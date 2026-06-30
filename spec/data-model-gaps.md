# Clinical Data Model Gap Analysis

_Extends: `reference/brook_data_model_gaps.md` (sections extended: MongoDB — Persona, PAI-184 Status, ICD-10 Location Inventory, Open Questions)_

> **Generated:** 2026-06-30
> **Agent:** gap-agent
> **Repos scanned:** brook-backend (`/tmp/brook-backend`, depth=1 clone, HEAD = commit `1485fa1` — PR #1810); fonzie (`/tmp/fonzie`, depth=1)
> **Method:** direct file reads + grep; all claims cite file paths or are flagged as assumptions

---

## Entity Status Table

| Entity | Brook Storage Today | Status | FHIR R4 Resource | Pillar(s) | Phase Needed |
|--------|--------------------|----|-----------------|-----------|--------------|
| PersonaDiagnosis | `persona.diagnoses[]` (embedded) | **EXISTS — canonical** | Condition | CCDA (Phase 1a), Bulk FHIR (Phase 3) | Phase 1a inbound write path |
| PersonaEncounter | None | **MISSING** | Encounter | CCDA (Phase 1a) | Phase 1a |
| PersonaMedication | `patient_care_plans.current_medications[]` (care plan section) | **PARTIAL — not discrete** | MedicationRequest | CCDA (Phase 1a) | Phase 1a |
| PersonaProblem | `patient_care_plans.problem_list` (care plan section) | **PARTIAL — not discrete** | Condition (problem-list-item) | CCDA (Phase 1a) | Phase 1a |
| PersonaAllergy | `patient_care_plans.allergies` (care plan section) | **PARTIAL — not discrete** | AllergyIntolerance | CCDA (Phase 1a) | Phase 1a |
| PersonaLab | `activity` collection (device-sourced only; A1c, BG per ActivityType) | **PARTIAL — device only, no EHR labs** | Observation (laboratory) | CCDA (Phase 1a), Bulk FHIR (Phase 3) | Phase 1a |
| PersonaVital | `activity` collection (device-sourced BP, weight, BG readings) | **PARTIAL — device only, no EHR historical** | Observation (vital-signs) | CCDA (Phase 1a), Bulk FHIR (Phase 3) | Phase 1a |
| Generic Clinical Observation | Redox `Observation` model (wire-only, no canonical storage) | **MISSING — no persistent canonical store** | Observation | CCDA (Phase 1a) | Phase 1a |

---

## Per-Entity Findings

### 1. PersonaDiagnosis

**Status:** EXISTS — canonical, PAI-184 CONFIRMED MERGED

**PAI-184 git verification:**
- The depth-1 clone of brook-backend (`HEAD = 1485fa1`, PR #1810) includes the fully merged PAI-184 code.
- `PersonaDiagnosis.java` exists at `/tmp/brook-backend/src/main/java/ai/brook/data/persona/diagnosis/PersonaDiagnosis.java`
- `DiagnosisSource.java` exists at `/tmp/brook-backend/src/main/java/ai/brook/data/persona/diagnosis/DiagnosisSource.java`
- The seed gap doc's statement "NOT IN MAIN as of last check" is now **refuted** — PAI-184 is merged.
- Note: only one commit is visible in the depth-1 clone (PR #1810). The specific PAI-184/PR #1611 merge commit is not visible in the shallow history. The existence of the class files on master/HEAD is the confirmation.

**Current shape:**
- File: `src/main/java/ai/brook/data/persona/diagnosis/PersonaDiagnosis.java` (lines 1–73)
- Embedded in `Persona.diagnoses[]`, stored in `persona` collection under Mongo key `diagnoses`
- Fields: `diagnosis_id` (UUID), `icd10_code`, `display_name_snapshot`, `display_name_resolved_at` (Instant), `source` (DiagnosisSource enum), `source_reference_id` (@Nullable), `assigned_at` (Instant), `assigned_by_persona_id` (@Nullable), `inactive_at` (@Nullable), `inactive_by_persona_id` (@Nullable)
- `isActive()` method: returns `inactiveAt == null`
- Annotations: `@JsonNaming(SnakeCaseStrategy)`, Lombok `@Builder @Getter @Setter @NoArgsConstructor @AllArgsConstructor`

**DiagnosisSource enum** (file: `src/main/java/ai/brook/data/persona/diagnosis/DiagnosisSource.java`):
Values: `PAP`, `REDOX`, `MANUAL`, `MIGRATION`, `OTHER`

**Gap vs FHIR R4 Condition:**
- Missing: `clinicalStatus` (active/inactive present via `isActive()` but not typed as FHIR CodeableConcept)
- Missing: `verificationStatus` (confirmed/unconfirmed/entered-in-error — FHIR required)
- Missing: `category` (problem-list-item vs encounter-diagnosis vs health-concern)
- Missing: `onsetDateTime` / `onsetAge` (EHR onset date)
- Missing: `recordedDate` (maps to `assignedAt` — available)
- Missing: `recorder` reference (maps to `assignedByPersonaId` — available)
- Missing: `abatementDateTime` (maps to `inactiveAt` — available)
- Missing: SNOMED codes — current store is ICD-10 only; FHIR Condition.code allows both
- **ATHENA_CCDA source value not in DiagnosisSource enum** — current values are PAP/REDOX/MANUAL/MIGRATION/OTHER. Must add `ATHENA_CCDA` and `ATHENA_BULK_FHIR` for Phase 1a/3 inbound writes.

**Persistence decision:** Discrete model exists. Write path needed for CCDA ingest (`source = ATHENA_CCDA`). No new collection — write to `persona.diagnoses[]` via existing `PersonaDiagnosisService`.

**Pillar dependency:** CCDA inbound (Phase 1a), Bulk FHIR (Phase 3).

**Recommended sequence:** Phase 1a — add `ATHENA_CCDA` to `DiagnosisSource` enum; implement CCDA → PersonaDiagnosis mapper in integration layer. Existing service and controller are the write target.

---

### 2. PersonaEncounter / Encounter

**Status:** MISSING — no Encounter model anywhere in brook-backend

**Evidence:** Exhaustive search of `/tmp/brook-backend/src/main/java/ai/brook/` returned zero files matching `PersonaEncounter`, `class.*Encounter`, or `Encounter ` (excluding Redox wire models). The `activity` collection tracks device readings and medication adherence events — it does not represent clinical encounters.

The Redox API model `Visit.java` (`src/main/java/ai/brook/api/rpm/emr/redox/api/model/common/Visit.java`) captures visit metadata in transit from Redox ORM orders (visitNumber, visitDateTime, attendingProvider, location) but this is a wire-layer DTO — it is NOT persisted to any MongoDB collection. Confirmed by absence of `@Document` annotation and no `MongoTemplate` or `Repository` references for this class.

The seed gap doc `Appointment.java` (collection `appointments`) is a care coordination appointment scheduler record, NOT a clinical encounter record. It tracks scheduled visits by Brook care team, not clinical visit history from EHR.

**FHIR R4 requires:** `Encounter` resource — class (ambulatory/inpatient), status, type, period, participant (provider), reasonCode (ICD-10), serviceProvider (Organization ref), subject (Patient ref).

**Persistence decision needed:** Decision required between:
1. **Discrete `PersonaEncounter` model** — new collection (recommended for CCDA inbound; enables querying by encounter date and type)
2. **Document reference** — store raw CCDA encounter section as BSON Document, resolve lazily (simpler short-term, harder to query)
3. **Hybrid** — store key index fields (date, type, visitNumber) discretely, blob the rest

**Pillar dependency:** CCDA inbound (Phase 1a). CCDA from athena includes encounter history (C-CDA section: encounters). This is the primary use case for Phase 1a dual-screening reduction.

**Recommended sequence:** Phase 1a — create `PersonaEncounter` collection. PROPOSAL file: `spec/data-model-proposals/PersonaEncounter.java`.

---

### 3. PersonaMedication / Medication

**Status:** PARTIAL — exists as unstructured text strings in care plan section; NOT discrete

**Current shape:**
- File: `src/main/java/ai/brook/api/caremanagement/model/CurrentMedications.java` (lines 1–38)
- Embedded in `PatientCarePlans.currentMedications` → stored in `patient_care_plans` collection under key `current_medications`
- Nested `Medication` record: `medication` (String — free text name), `dosage` (String — free text), `frequency` (String — free text), `comments` (String), `startDate` (Date)
- `CurrentMedications` extends `Audit` (reviewed/updated/created audit fields)
- No `rxNorm` code, no `ndc` code, no structured dose, no `doseAndRate`, no prescriber, no dispense info

Additionally, `Persona.medication` (String field at `src/main/java/ai/brook/data/persona/Persona.java`) is a single freetext string for medication — deprecated pattern predating care plans.

The new `medication_routines` collection (confirmed in fonzie spec `2025-11-03-mongodb-collections-analysis.md` line 28–30) tracks adherence routines for patient-reported medication tracking. This is different from EHR medication list.

**FHIR R4 requires:** `MedicationRequest` (prescribed medications) or `MedicationStatement` (patient-reported). Key required fields: `medication` (CodeableConcept with RxNorm), `subject` (Patient ref), `status`, `intent`, `dosageInstruction` (structured: dose, route, frequency), `authoredOn`, `requester` (prescriber).

**Gap:** Free text strings cannot be mechanically mapped to FHIR `MedicationRequest.medication[x]` without RxNorm lookup. CCDA medication list section provides structured data (RxNorm, NDC, SIG text). A discrete `PersonaMedication` model is needed to receive this structured data from CCDA ingest without destroying it by collapsing to strings.

**Persistence decision needed:**
1. **New discrete collection** `persona_medications` (recommended for CCDA inbound; parallel to care plan section, not a replacement)
2. **Enhance existing care plan section** — add RxNorm code field to `CurrentMedications.Medication` and mark as EHR-sourced
3. **Hybrid** — keep care plan section for care team use; new discrete store for EHR-sourced medications; surface both in UI

**Pillar dependency:** CCDA inbound (Phase 1a).

**Recommended sequence:** Phase 1a — create `PersonaMedication` as a new top-level collection (not embedded, to allow querying). PROPOSAL file: `spec/data-model-proposals/PersonaMedication.java`.

---

### 4. PersonaProblem / Problem List

**Status:** PARTIAL — exists as unstructured text strings in care plan section; ICD-10 field present but no FHIR alignment

**Current shape:**
- File: `src/main/java/ai/brook/api/caremanagement/model/ProblemList.java` (lines 1–59)
- Embedded in `PatientCarePlans.problemList` → stored in `patient_care_plans` collection under key `problem_list`
- Nested `Condition` record: `condition` (String — free text name), `icd10Code` (String — stored as `icd10_code`), `diagnosisDate` (Date)
- Also contains `Surgery` (surgery, date, facility) and `TestProcedure` (date, test, valueOfTest)
- `ProblemList` extends `Audit`

**Note on naming:** Brook uses `ProblemList.Condition` as the class name for a problem list entry. This is distinct from `ai.brook.data.persona.Condition` (the legacy Profile.conditions Set used for eligibility classification). And from `PersonaDiagnosis` (the new canonical diagnosis store). Three overlapping concepts — see Open Questions.

**FHIR R4 requires:** `Condition` resource with `category = problem-list-item` (to distinguish from encounter-diagnosis). Key fields: `code` (CodeableConcept — ICD-10 or SNOMED), `subject`, `clinicalStatus`, `verificationStatus`, `onsetDateTime`, `recordedDate`.

**Gap:** The `icd10Code` field exists but `condition` is still free text. `diagnosisDate` maps to `onsetDateTime`. Clinical/verification status not captured. CCDA problem list section provides structured codes that would be collapsed to text strings today.

**Persistence decision needed:** Same three-way choice as medications: new discrete collection, enhance care plan section, or hybrid. However, the relationship between `PatientCarePlans.problemList` and `Persona.diagnoses[]` (PAI-184) must be resolved — they currently represent the same concept stored in two places.

**Pillar dependency:** CCDA inbound (Phase 1a).

**Recommended sequence:** Phase 1a — resolve the `problemList` vs `persona.diagnoses[]` duality first (see Open Questions). If `persona.diagnoses[]` is the canonical store, route CCDA problem list → `PersonaDiagnosis` via `source=ATHENA_CCDA`. If both are maintained, create `PersonaProblem` as a thin wrapper adding FHIR category. PROPOSAL file: `spec/data-model-proposals/PersonaProblem.java` (drafted as thin wrapper assuming `diagnoses[]` is canonical; Brook Backend team to confirm routing decision).

---

### 5. PersonaAllergy / AllergyIntolerance

**Status:** PARTIAL — exists as free-text strings in care plan section; no coding, no criticality, no reaction coding

**Current shape:**
- File: `src/main/java/ai/brook/api/caremanagement/model/Allergies.java` (lines 1–27)
- Embedded in `PatientCarePlans.allergies` → stored in `patient_care_plans` collection under key `allergies`
- Nested `Allergy` record: `allergen` (String — free text name), `reaction` (String — free text reaction description)
- `Allergies` extends `Audit`
- No allergy type (food/medication/environment), no criticality (mild/moderate/severe/life-threatening), no SNOMED/RxNorm allergen code, no onset date, no clinical status, no recorder

**FHIR R4 requires:** `AllergyIntolerance` resource. Key required fields: `patient` (ref), `code` (CodeableConcept — allergen, ideally SNOMED or RxNorm), `clinicalStatus`, `verificationStatus`. Key important fields: `type` (allergy vs intolerance), `category` (food/medication/environment/biologic), `criticality`, `reaction[].manifestation` (coded), `reaction[].severity`, `onsetDateTime`, `recorder`.

**Gap:** Both `allergen` and `reaction` are free text. CCDA allergy section provides coded allergen (RxNorm or NDF-RT) and coded reaction (SNOMED). Current model cannot receive or persist the coded data. This is a significant clinical safety concern — allergy criticality is clinically critical for medication decision-making.

**Persistence decision needed:** New discrete `PersonaAllergy` collection strongly recommended over enhancing the care plan section. Allergy information from EHR is authoritative clinical data that should be stored discretely, not only in a care plan document context.

**Pillar dependency:** CCDA inbound (Phase 1a).

**Recommended sequence:** Phase 1a. PROPOSAL file: `spec/data-model-proposals/PersonaAllergy.java`.

---

### 6. PersonaLab / Lab Results

**Status:** PARTIAL — device-sourced quantitative readings exist in `activity` collection; EHR-sourced lab results have no canonical store

**Current shape (device-sourced):**
- `Activity` collection (`src/main/java/ai/brook/data/activity/Activity.java`) stores device readings.
- `ActivityType` is sourced from `health.brook.devicebusdata.model.activity.ActivityType` (external dependency jar; source not in brook-backend tree). From usage context: includes `A1C`, `BLOOD_PRESSURE` (inferred from `A1C` reference at Activity.java:473 and `BLOOD_PRESSURE` pattern in Redox flowsheet mapping).
- `ActivityMetric` carries the numeric value and unit; `ActivitySource` identifies the device origin.
- `activity` is the RPM monitoring data store — A1c entered via device/patient-app, BP from Bodytrace/Withings/Telli devices, BG from glucometers.

**EHR-sourced labs:**
- No collection for EHR-sourced lab results found anywhere in brook-backend or fonzie.
- The Redox `Observation.java` (`src/main/java/ai/brook/api/rpm/emr/redox/api/model/flowsheets/Observation.java`) is a wire DTO for outbound flowsheet observations posted to Redox — it is NOT used for inbound lab storage.
- PAP `patient` table stores `last_a1c` (NUMERIC), `last_dbp` / `last_sbp` (NUMERIC), `last_gfr` (NUMERIC), `date_of_last_a1c`, `date_of_last_bp` — these are registration-time flat scalar fields, not a lab results history.

**FHIR R4 requires:** `Observation` resource with `category = laboratory`. Key fields: `code` (LOINC), `subject`, `status`, `effectiveDateTime`, `valueQuantity` (or `valueString`, etc.), `interpretation`, `referenceRange`, `performer`.

**Gap:** Brook has no mechanism to store discrete, EHR-sourced lab results with LOINC codes, reference ranges, or historical series. The CCDA lab results section (C-CDA LOINC-coded observations) cannot be persisted today.

**Persistence decision needed:**
1. **New discrete `PersonaLab` collection** — recommended; one document per lab result, enables querying by LOINC code and date range for A1c trending, GFR tracking
2. **Extend `activity` collection** — use `ActivityType.LAB` (if it exists) with new `source.type = ATHENA_CCDA`; leverages existing billing/display infrastructure but forces clinical lab data into a device-activity shape

**Pillar dependency:** CCDA inbound (Phase 1a), Bulk FHIR (Phase 3).

**Recommended sequence:** Phase 1a — create `PersonaLab` collection. PROPOSAL file: `spec/data-model-proposals/PersonaLab.java`.

---

### 7. PersonaVital / Vitals History

**Status:** PARTIAL — device-sourced current vitals exist in `activity` collection; EHR-sourced historical vitals have no canonical store

**Current shape:**
- Same `activity` collection as labs. Device-sourced BP, weight readings flow in via Withings, Bodytrace, A&D, Transtek, ForaCare, etc. (`ActivitySource.SourceType` at `ActivitySource.java:132-160`).
- The `ProviderDetails.latestActivities` map (`Map<ActivityType, Activity>`) provides last-seen activity per type — this is a snapshot, not history.
- PAP `patient` table stores `last_sbp`, `last_dbp`, `weight`, `bmi`, `height` — registration-time flat scalars, not a vital signs history.

**Distinction to flag:** Brook's `activity` collection IS the device vital signs time-series — it is fit for purpose for RPM billing (device readings with timestamps). However it was not designed for EHR-sourced historical vitals, which may predate device enrollment and have a different source, format (nurse-entered vs. device-transmitted), and clinical context (office visit vs. home monitoring).

**FHIR R4 requires:** `Observation` with `category = vital-signs`. Same shape as lab, different category and LOINC codes (e.g., LOINC 8480-6 for systolic BP, 29463-7 for body weight).

**Gap:** The `activity` collection's `ActivitySource` does not include `ATHENA_CCDA` or `ATHENA_BULK_FHIR` as source types. Adding new source types to `ActivitySource.SourceType` enum is the minimum change; however, the shape of `activity` (optimized for streaming device data, billing queries) may not be the right home for EHR-sourced historical vital sign records. This requires a persistence decision.

**Persistence decision needed:**
1. **Extend `activity` collection** — add `ATHENA_CCDA` / `ATHENA_BULK_FHIR` to `ActivitySource.SourceType`; EHR vitals become activities with a new source. Lowest friction, reuses billing/display infrastructure.
2. **New `PersonaVital` collection** — separate EHR-sourced history from device readings; cleaner FHIR alignment but requires new display path.

**Pillar dependency:** CCDA inbound (Phase 1a), Bulk FHIR (Phase 3).

**Recommended sequence:** Phase 1a — extend `ActivitySource.SourceType` with `ATHENA_CCDA` as the minimum viable change. Full `PersonaVital` collection may not be needed if the activity collection extension is acceptable to the DNA/Backend team. PROPOSAL file: `spec/data-model-proposals/PersonaVital.java` drafted for the discrete collection option.

---

### 8. Generic Clinical Observation Pattern

**Status:** MISSING as a canonical persistent store — partial as a wire-layer DTO only

**Evidence:**
- `src/main/java/ai/brook/api/rpm/emr/redox/api/model/flowsheets/Observation.java` — wire DTO for outbound Redox flowsheet posting. Fields: `status`, `description`, `valueType`, `value`, `codeset`, `code`, `units`, `dateTime`, `referenceRange`, `observer`, `notes`, `abnormalFlag`. This is OUTBOUND only — Brook POSTS device readings to Redox in this format; Redox does not send observations back via this model.
- No `@Document` or persistence annotation. No repository or DAO. Not stored in Mongo.

**FHIR R4 pattern:** The `Observation` resource is the universal container for both lab results and vital signs in FHIR. A generic `ClinicalObservation` base shape (with category discriminating lab vs. vitals) is a cleaner design than two separate collections.

**Recommended sequence:** Phase 1a — decide whether `PersonaLab` and `PersonaVital` share a common base model or are separate collections. If a shared `ClinicalObservation` base is used, define it as an abstract parent. This decision gates the Java class proposals.

---

## Persistence Decision Questions

These become Key Decisions in the Linear spec:

1. **[Diagnosis store routing] Is `persona.diagnoses[]` (PAI-184) the canonical store for all ICD-10 diagnosis data, replacing `PatientCarePlans.problemList.Condition`?** If yes: CCDA problem list maps to `PersonaDiagnosis` with `source=ATHENA_CCDA`. If no: two parallel stores exist and a sync/reconciliation policy is needed.

2. **[Medication discreteness] Does EHR-sourced medication data from CCDA land in a new discrete `PersonaMedication` collection, or does it extend `CurrentMedications.Medication` with RxNorm fields?** Answer determines whether Phase 1a adds a new collection or modifies an existing embedded document.

3. **[Vitals routing] Do EHR-sourced historical vitals (from CCDA) go into the existing `activity` collection (with new `ATHENA_CCDA` source type), or a new `PersonaVital` collection?** Activity collection reuse is lowest friction but may confuse RPM billing queries that assume `activity` = device readings.

4. **[Lab discreteness] Are EHR lab results (A1c, GFR, HbA1c from CCDA) stored in a new `PersonaLab` collection or in the `activity` collection?** PAP scalar fields (`last_a1c`, `last_gfr`) are single-value snapshots — a lab collection enables historical series and LOINC-coded queries.

5. **[Allergy authority] Is EHR allergy data from CCDA authoritative over care team-entered allergy data?** The answer drives merge/override semantics in the CCDA ingest mapper.

6. **[Encounter necessity in Phase 1a] Does the Phase 1a POCAR UI need to display encounter history, or is encounter data only needed for Phase 3 Bulk FHIR population context?** If Phase 1a display requires it, `PersonaEncounter` must ship in Phase 1a. If display-only is acceptable from raw CCDA, deferring the discrete model to Phase 3 is possible.

---

## Sequencing Plan

### Phase 1a — CCDA Inbound (minimum model changes required)

**Mandatory before CCDA mapper can write any data:**
1. Add `ATHENA_CCDA` to `DiagnosisSource` enum — 1-2 hours, no schema migration
2. Create `PersonaEncounter` collection — new `@Document` class (see proposal)
3. Resolve persistence decision #1 (diagnosis routing) with Brook Backend team

**Strongly recommended (unless persistence decision defers them):**
4. Create `PersonaMedication` collection — new `@Document` class (see proposal)
5. Create `PersonaAllergy` collection — new `@Document` class (see proposal)
6. Create `PersonaLab` collection OR add `ATHENA_CCDA` source to `activity` — pending decision #4

**Can be deferred to Phase 3 if decision #6 is "encounter display not needed in 1a":**
- `PersonaVital` discrete collection (extend `ActivitySource.SourceType` as interim)

### Phase 3 — Bulk FHIR (additional model maturity)

- FHIR `verificationStatus` on `PersonaDiagnosis` (needed for FHIR-compliant Condition resource)
- Add `ATHENA_BULK_FHIR` to `DiagnosisSource` enum
- Ensure `PersonaEncounter`, `PersonaMedication`, `PersonaAllergy`, `PersonaLab` all support `ATHENA_BULK_FHIR` source

### Phase 4+ (post-v1)

- SNOMED coding on `PersonaDiagnosis` (ICD-10 only is acceptable for v1)
- Full `PersonaVital` collection if activity-collection extension proves insufficient

---

## Open Questions for Brook Backend / DNA Team

- **[Critical] `PersonaDiagnosis` vs. `PatientCarePlans.problemList` duality.** Both store chronic conditions with optional ICD-10 codes. PAI-184's intent was to make `persona.diagnoses[]` the canonical store. Has the migration of `problemList` data to `diagnoses[]` been decided, scoped, or executed? Is there a ticket? This is a blocking decision for Phase 1a CCDA routing.

- **[Critical] DiagnosisSource enum extension.** `ATHENA_CCDA` and `ATHENA_BULK_FHIR` source values need to be added before any integration-layer code can write to `persona.diagnoses[]`. Is this a Backend ticket or can the integration layer own this enum addition?

- **[Activity collection] Can `ActivitySource.SourceType` safely receive new values (`ATHENA_CCDA`, `ATHENA_BULK_FHIR`) without breaking existing RPM billing queries that assume all `activity` records are device-sourced?** The billing DAOs (`BillingActivity.java`, dbt billing models) may filter or aggregate on source type.

- **[Allergy] Does Brook's clinical team consider care team-entered allergy data authoritative, or should EHR-sourced data override/supplement it?** This is a clinical workflow question, not just an engineering decision.

- **[Encounter] The Redox wire model `Visit.java` is not persisted.** When Brook receives Redox ORM orders, do any encounter-level fields (visitNumber, visitDateTime) get stored anywhere? Confirmed from code: `visitNumber` and `emrOrderDate` land in `ProgramEnrollment` and `ProviderDetails` — but that is order context, not clinical encounter history.

- **[Medication routines] The `medication_routines` collection (confirmed in fonzie collections analysis, 2025-11-03) is the new medication adherence system.** How does it relate to `CurrentMedications` in the care plan? Is `medication_routines` the patient-facing adherence tracker while `CurrentMedications` is the care team medication list? Confirm separation before designing `PersonaMedication`.

- **[ETL propagation] Does `PersonaTransformer` in ETL-service propagate `persona.diagnoses[]` changes to Snowflake/Customer.io downstream?** From the seed gap doc: NOT FOUND as of the last check. If diagnoses are not in the ETL change stream, Snowflake/dbt models will not see new CCDA-sourced diagnoses.

- **[Lab history] A1c and GFR values exist as flat scalars in PAP `patient` table (`last_a1c`, `last_gfr`, `date_of_last_a1c`, `date_of_gfr`).** Is there a migration plan to move these into a discrete lab history store, or are they maintained indefinitely as registration-time snapshots?
