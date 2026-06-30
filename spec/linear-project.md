# Integration PX: athena + Griffin v1 — Linear Project Spec

| Field | Value |
|-------|-------|
| Project | Integration PX: athena + Griffin v1 |
| Owner | |
| Teams | Backend, DNA, Care Platform |
| Status | Draft |
| Linear | [link TBD] |
| Design | N/A |
| Testing Plan | [link TBD] |

---

## Problem

The Redox integration was built without a platform layer, and the seam bugs are evidence of that cost. AAR-247 (lead provider not written for existing patients) and AAR-329 (RPM consent auto-stamped for CCM-only clinics, generating incorrect billing) are open PRs as of 2026-06-30 — PR #1717 and PR #1758 respectively — still in-flight, not historical artifacts. Both bugs trace to mapping logic and ingest semantics embedded in `RedoxService.java` (82KB of inline transform code) rather than in a defined platform layer. The Persona model confirms the same pattern: `Persona.diagnoses[]` (PAI-184, merged), `PatientCarePlans.problemList`, and PAP-table registration scalars (`last_a1c`, `last_gfr`) all store overlapping clinical concepts with no canonical routing — a registration-shaped data model that was never redesigned for clinical data ingest. Meanwhile, `AthenaService.java` is already posting monthly PDF bundles to athena's `/clinicaldocument` endpoint for Griffin, with `documentTypeId=440672` hardcoded and a `//TODO` comment marking it — live shipping code, fragile, with no event-driven trigger and no mapping config. The athena work builds the platform that should have preceded Redox.

---

## Scope

Two workstreams. Both required for v1 athena. Neither ships alone for Phase 1a.

---

### Workstream 1: Integration Platform

**P0 — Foundation**
Build the partner-agnostic platform layer: event bus contracts, auth/secrets scaffolding, base HTTP client (wire `ExponentialBackoffInterceptor.java` into OkHttp builders — it exists but is disconnected from production EMR calls; findings.md, recon summary #5), mapping config schema (YAML or JSON, partner-keyed; zero existing implementation, genuine greenfield; findings.md "Mapping config schema"), and observability via Integration Health Dashboard. The "Integration Event Worker (Go)" referenced in the build plan was not found in any scanned repo (findings.md, "Plan Assumptions I Could Not Verify" #1) — the event substrate decision is open (see Key Decision 7).

**P1a — CCDA Inbound**
Build GET `/v1/{practiceid}/ccda/{patientid}/ccda` retrieval, CDA parser, CCDA adapters (encounter adapter, medication adapter, allergy adapter, diagnosis adapter, lab adapter, vital adapter), and POCAR trigger (nurse-on-demand pull). Zero existing code for any of these components; the athena OAuth2 client in `AthenaApiService.java` is the only reusable piece (findings.md, "CCDA Inbound"). The `last_pocar_opened_at` signal already propagates through care-nexus on chart open and is the natural hook, but nothing downstream of it triggers a data fetch today (findings.md, "POCAR / Care Team UI"). Requires `brook-web-app` (Angular) changes plus a new `brook-backend` API endpoint.

**P1b — Clinical Document Upload (refactor, not greenfield)**
Refactor `AthenaService.java` and `AthenaApi.java` to replace hardcoded `documentTypeId=440672` with mapping config, add event-driven trigger (currently batch-scheduled via `GenericQueueProcessor` with `GENERATE_BUNDLED_REPORT` action), and upgrade idempotency key from filename-based to event-version-based. This code is live and shipping to Griffin today. The migration plan and parallel-run window are open decisions (Key Decision 9).

**P2 — Orders**
Build the athena orders ingest path: Brook drafts order, physician signs in athena task queue, Brook receives signed-order signal, patient activates. Redox ORM ingest (`RedoxController`, `RedoxOrderQueueItem` queue, 10-minute scheduled processor) is the correct precedent pattern. No athena orders code exists (findings.md, "Orders"). Blocked on clinician verification of the orders workflow assumption and Andrew's review of dedup logic (Key Decisions 5 and 6).

**P3 — Bulk FHIR Patient Population Ingest**
Build athena's three-step async export pattern: initiate export, poll status, retrieve manifest, download NDJSON. Nightly cadence; idempotent upsert into Brook patient model; MRN + provider ID + Brook patient ID + DOB matching. Eliminates the CSV/SFTP path for Griffin.

**P4 — Notes and Escalations**
Build POST `/note` triggered by escalation domain events. `AthenaService` does not implement `EmrService.sendPatientNote()` today; `AthenaApi` has no `/note` endpoint method (findings.md, "Notes / Escalations"). Reuses the store pattern established in P1b.

**P5 — Billing: Real-Time Charge Posting**
Build POST `/procedure` triggered by `ChargePosted` events with correct CPT codes per program. Fully greenfield. Current billing path is the monthly PDF bundle via `AthenaService.sendBundleReport()` — that remains in parallel-run until finance sign-off. `OutboundGate` gating for the new charge-posting path requires a separate enum value or verification that the existing `ATHENA` gate covers new endpoints (findings.md, "Plan Assumptions I Could Not Verify" #4).

---

### Workstream 2: Clinical Data Model Expansion

All entities below are required before the CCDA mapper can write data. Sequence: P1a minimum model changes must land before CCDA parser implementation begins.

| Entity | Brook Storage Today | Status | Phase Needed |
|--------|--------------------|----|--------------|
| PersonaDiagnosis | `persona.diagnoses[]` (embedded) | EXISTS — canonical (PAI-184 merged) | Phase 1a: add write path + `ATHENA_CCDA` enum value |
| PersonaEncounter | None | MISSING | Phase 1a |
| PersonaMedication | `patient_care_plans.current_medications[]` (free text strings) | PARTIAL — not discrete, no RxNorm | Phase 1a |
| PersonaProblem | `patient_care_plans.problem_list` (free text, ICD-10 present) | PARTIAL — not discrete; duality with `persona.diagnoses[]` unresolved | Phase 1a (after Key Decision 2) |
| PersonaAllergy | `patient_care_plans.allergies` (free text allergen + reaction) | PARTIAL — no coding, no criticality | Phase 1a |
| PersonaLab | `activity` collection (device-sourced A1c, BG only) | PARTIAL — device only, no EHR labs | Phase 1a (pending Key Decision 1) |
| PersonaVital | `activity` collection (device-sourced BP, weight) | PARTIAL — device only, no EHR historical | Phase 1a (pending Key Decision 4) |

Source: data-model-gaps.md, Entity Status Table.

---

### Out of Scope

- Full claims submission. Billing scope is eligibility verification and real-time CPT charge posting only. No payer-side claims adjudication.
- Non-athena EHR adapters. v1 is athena-only. The platform is designed to accept additional partners; that is a future cycle.
- PHI storage in the integration layer itself. The integration layer is a pass-through and routing layer. Clinical data lands in Brook's canonical Persona/PatientCarePlans collections via existing services.
- Device readings push to athena. No agreed standard, no clear value path.
- Redox re-platforming onto the new foundation. Future consideration, separate decision.

---

## Key Decisions

THE CRITICAL ARTIFACT. Each decision below changes the build if it flips. Decisions that do not change the build have been excluded.

---

**Decision 1: Clinical data persistence pattern per entity**
Question: For each CCDA-sourced clinical entity (Encounter, Medication, Allergy, Lab, Vital), does retrieved data land in a new discrete collection, in an extended existing collection, or in a hybrid per-entity store?
Options:
  A. New discrete collection per entity (PersonaEncounter, PersonaMedication, PersonaAllergy, PersonaLab) — clean FHIR alignment, new collections to maintain, new display paths required.
  B. Extend existing collections (enhance `patient_care_plans` embedded documents with coded fields, extend `activity` with new SourceType values) — lowest friction, reuses billing infrastructure, may pollute RPM billing queries that assume `activity` = device readings only.
  C. Hybrid: discrete collections for Encounter and Allergy (clinical safety case); extend existing for Medication and Vital — balances risk against friction.
Owner: Constantine (Backend/DNA)
Blocker: No CCDA adapter can be implemented until persistence targets are defined for each entity.
Impact if deferred: The CCDA adapters ship without write targets. Data is parsed and discarded or stored as raw BSON blobs with no queryable structure. Phase 1a exit criteria (encounter and medication data shows in POCAR UI) cannot be met.

---

**Decision 2: PersonaDiagnosis vs. PersonaProblem duality**
Question: Is `persona.diagnoses[]` (PAI-184) the canonical store for all chronic condition data, replacing `PatientCarePlans.problemList.Condition` as the write target for CCDA problem list ingest?
Options:
  A. `persona.diagnoses[]` is canonical. CCDA problem list section maps to `PersonaDiagnosis` with `source=ATHENA_CCDA`. `PatientCarePlans.problemList` becomes read-only legacy, migrated or deprecated on a separate ticket.
  B. Both stores are maintained in parallel. CCDA problem list maps to `PersonaProblem` (thin wrapper over `problemList`) and separately to `PersonaDiagnosis`. A reconciliation policy is required.
Owner: Constantine (Backend/DNA) — flagged as the single most important question for these teams in data-model-gaps.md, "Open Questions"
Blocker: CCDA problem list mapper cannot be written. Routing logic for CCDA Condition resources is undefined.
Impact if deferred: Two separate write paths are implemented without a canonical owner. Downstream queries (dbt, Customer.io via ETL-service) read from an inconsistent source depending on which path ran last.

---

**Decision 3: DiagnosisSource enum extension**
Question: Who owns the addition of `ATHENA_CCDA` and `ATHENA_BULK_FHIR` values to `DiagnosisSource.java`, and when does it land relative to Phase 1a?
Options:
  A. Backend owns the enum change. Ships as a prerequisite ticket before Phase 1a integration code begins.
  B. Integration layer team owns the enum change as part of Phase 1a kickoff. Backend reviews.
Owner: Constantine (Backend)
Blocker: Any integration-layer code that writes to `persona.diagnoses[]` will fail enum validation until these values exist. This is a 1-2 hour change (data-model-gaps.md, "Sequencing Plan, Phase 1a, item 1") but it must ship before integration code can be tested end-to-end.
Impact if deferred: Integration layer code cannot write diagnoses in Phase 1a. The diagnosis adapter is dead code until the enum ships.

---

**Decision 4: PersonaVital persistence**
Question: Do EHR-sourced historical vital signs (from CCDA vital-signs section) go into the existing `activity` collection with new `ActivitySource.SourceType.ATHENA_CCDA` values, or a new `PersonaVital` collection?
Options:
  A. Extend `activity` collection — add `ATHENA_CCDA` and `ATHENA_BULK_FHIR` to `ActivitySource.SourceType`. Lowest friction, reuses existing billing/display infrastructure.
  B. New `PersonaVital` collection — separates EHR-sourced history from device readings. Cleaner FHIR alignment but requires a new display path and care-nexus propagation path.
Owner: Constantine (Backend/DNA)
Blocker: CCDA vital-signs adapter has no write target until this is resolved.
Impact if deferred: EHR-sourced vitals are either discarded, stored as raw BSON, or written to `activity` by default. If written to `activity` without explicit decision, dbt billing models that assume all `activity` records are device-sourced may count EHR-historical vitals in RPM billing calculations (data-model-gaps.md, "Open Questions" — activity collection safe extension question).

---

**Decision 5: Orders workflow model**
Question: Does Griffin v1 use the classical order model (physician places order in athena), the postmodern model (Brook PSM cultivates relationship, physician signs post-hoc in athena task queue), or both?
Options:
  A. Postmodern only — Brook drafts, physician signs in athena task queue. Single flow to implement.
  B. Both — two distinct ingest paths, two dedup strategies, two order status polling designs.
Owner: (Jason to fill — requires clinician verification call per build plan, "Phase 0 exit criteria")
Blocker: Phase 2 scope cannot lock. API endpoints, dedup logic, order status polling design, and patient activation trigger all differ between models.
Impact if deferred: Phase 2 implementation starts with an undefined workflow model. Engineering builds for one assumption; if the assumption flips after development starts, the order state machine and dedup logic require rework.

---

**Decision 6: Orders dedup logic**
Question: How does Brook deduplicate orders it has already sent to athena against orders it generates for the same patient in a new cycle?
Options:
  A. Extend `EmrLog` dedup mechanism (currently `(personaId, providerOfficeId, month, type)`) with an order-specific compound key. Lowest friction, reuses existing infrastructure.
  B. New idempotency key store specific to orders, using `{patientId}:{orderId}:{orderVersion}` — more precise, consistent with the plan's proposed key scheme, new infrastructure.
Owner: (Andrew Rosenthal per build plan; Jason to fill)
Blocker: Phase 2 implementation. Duplicate orders risk double-activating patients or generating duplicate billing charges.
Impact if deferred: Dedup is implemented ad-hoc per engineer judgment. Replay safety cannot be verified per the Phase 2 exit criteria.

---

**Decision 7: Event substrate for integration layer**
Question: Which event substrate does the integration platform use to emit and consume events?
Options:
  A. AWS SQS — used by services-data for device data (`QueueAlias.BROOK`, `BROOK_PLUS`, `NOTIFICATIONS`) and by brook-backend `DataBusScheduler`. Existing patterns in brook-backend.
  B. MongoDB CDC — used by care-nexus, watching `persona` and related collections. No SQS involved.
  C. Redis Streams (Valkey) — used by data-platform CIO service. Different infra from SQS entirely.
  D. Kafka — EDA-native, durable log, replay-safe. No existing Brook precedent found in scanned repos; would require new infra. PM preference.
Owner: Backend + infra (architecture decision). PM preference is Kafka / EDA (Option D) but defers to engineering on feasibility and infra lift.
Blocker: Phase 0 Foundation scope. Event bus contracts cannot be defined until the substrate is selected. The build plan states "existing SQS-backed worker pattern is the substrate" but recon found three separate substrates in production (findings.md, "Event bus substrate"). The "Integration Event Worker (Go)" cited in the plan was not found in any scanned repo (findings.md, "Plan Assumptions I Could Not Verify" #1).
Impact if deferred: Phase 0 exits without a committed event contract. Phases 1a-5 all emit events — if the substrate is undecided, integration event handlers are prototyped on an assumed substrate that may not be the one infra provisions.

---

**Decision 8: Mapping config format**
Question: Is the mapping config schema YAML, JSON, or a custom DSL?
Options:
  A. YAML — the build plan references YAML as the leading option; human-readable, diff-friendly, widely understood.
  B. JSON — machine-readable, strict schema validation, consistent with Brook's existing MongoDB document model.
  C. Custom DSL — maximum expressiveness for complex transforms, highest build cost, no existing precedent in Brook repos.
Owner: Backend (tech lead)
Blocker: Phase 0 exit criterion is "mapping config schema reviewed and Griffin's config v0 in repo." Schema format must be decided before the Griffin v0 config file can be written.
Impact if deferred: Griffin's mapping lives as hardcoded transforms in the integration layer (the anti-pattern the plan is replacing). The Phase 0 exit criterion is not met.

---

**Decision 9: Phase 1b migration plan**
Question: What is the migration path for the existing live `AthenaService.sendBundleReport()` code (hardcoded `documentTypeId=440672`, batch-scheduled trigger) to the new mapping-config-driven, event-driven architecture?
Options:
  A. Parallel run — new event-driven path ships alongside the existing batch job; batch job is disabled after a defined validation window. Lower risk; Griffin continues receiving documents during migration.
  B. Cutover — new path replaces the batch job in a single deploy. Higher risk; if the new path has a defect, Griffin stops receiving documents until hotfix.
Owner: Backend
Blocker: Phase 1b implementation planning. A parallel-run window changes the required validation infrastructure (needs comparison logging to verify new path produces identical output to old path).
Impact if deferred: The live job continues running with hardcoded values. A Phase 1b deploy without a migration plan risks either a document gap (cutover without validation) or indefinitely running two paths (no decommission plan for the old job).

---

**Decision 10: OutboundGate coverage for new athena endpoints**
Question: Does the existing `ATHENA` `OutboundGate` enum value gate all new endpoints (CCDA GET, orders POST, billing POST), or does each new endpoint type require its own gate value?
Options:
  A. Single `ATHENA` gate covers all athena endpoints. Simpler; consistent with current gating of `BUNDLED_REPORT` under `ATHENA`.
  B. Separate gate values per endpoint type (e.g., `ATHENA_CCDA`, `ATHENA_ORDERS`, `ATHENA_BILLING`). Finer-grained control; allows disabling billing without disabling CCDA; higher maintenance surface.
Owner: Backend
Blocker: Any new athena endpoint that ships without explicit gate coverage is ungated in production by default. The `OutboundGate` gating of `BUNDLED_REPORT` is confirmed in `GenericQueueProcessor.java:34-37` (findings.md, "Clinical Document Upload"); coverage for new endpoints needs explicit decision.
Impact if deferred: New athena endpoints may fire in production for partners not yet contracted for those capabilities. This is a compliance risk for a gated integration.

---

## What This Unlocks

- Dual-screening elimination for Griffin nurses. Today, nurses open patient charts in both POCAR and athena to reconcile medication lists, allergy histories, and encounter context. CCDA inbound pulls that data into POCAR on chart open.
- Automated clinical document delivery. Phase 1b removes the Partner Ops manual upload workflow (estimated 7 hrs/month saved) and satisfies the compliance re-assertion requirement confirmed by outside counsel.
- Replicable EHR onboarding. Once P0 and P1 ship, adding a second athena partner is a mapping config change, not an engineering sprint. Epic, Cerner, and future EHRs become adapters on the same foundation.
- Population-level enrollment automation. Phase 3 Bulk FHIR ingest retires the Griffin CSV/SFTP path and the class of PAP data quality tickets it generates (AAR-209, AAR-214, PAI-15, ENG-468).
- Real-time billing signal. Phase 5 replaces the monthly batch PDF billing artifact with per-patient, per-encounter charge posting — a prerequisite for any expansion beyond Griffin's current batch-oriented finance workflow.

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| EHR integrations live (direct API, not Redox) | 0 | 1 (athena, v1) |
| Clinical entities in Persona with discrete EHR-sourced store | 1 (PersonaDiagnosis, PAI-184) | 7 (Diagnosis, Encounter, Medication, Problem, Allergy, Lab, Vital) |
| Hardcoded athena integration values in production code | 1 (`documentTypeId=440672`, `AthenaService.java:52`) | 0 |
| Open Redox seam-bug PRs (AAR-247, AAR-329) | 2 open (PR #1717, PR #1758) | 0 (closed or migrated to platform layer) |
| Partner Ops manual upload hours per month (Griffin care plans) | ~7 hrs/month (assumption from build plan; needs verification) | 0 |
| Griffin care plans auto-delivered per month | 0 (manual today) | 192+ |
| CCDA ingest latency (nurse chart open to data available in POCAR) | N/A | TBD (target: under 10 seconds for on-demand pull; assumption, needs verification against athena API SLA) |
| Event substrates in production for integration workloads | 3 (SQS, MongoDB CDC, Redis Streams — findings.md) | 1 committed substrate for integration layer events |
| Mapping config schema instances in repo | 0 | 1 (Griffin v0 config) |

---

## Appendix: Linear Epic and Ticket Structure

### Epic Structure

| Epic Title | Description | Phase | Status |
|------------|-------------|-------|--------|
| P0: Integration Platform Foundation | Build partner-agnostic event bus contracts, auth scaffolding, HTTP client wiring, mapping config schema, and observability. | P0 | Greenfield (no existing implementation; ExponentialBackoffInterceptor wiring is a 1-day task not a build) |
| P1a: CCDA Inbound | Build GET CCDA retrieval, CDA parser, CCDA adapters (encounter, medication, allergy, diagnosis, lab, vital), and POCAR on-demand trigger. | P1a | Greenfield (OAuth2 client reused; all else new) |
| P1b: Clinical Document Upload | Refactor live AthenaService.java and AthenaApi.java to mapping-config-driven, event-driven architecture. | P1b | Refactor of live shipping code |
| P2: Orders | Build athena orders ingest and patient activation flow. | P2 | Greenfield; blocked on external decisions |
| P3: Bulk FHIR Patient Population Ingest | Build three-step async FHIR export, nightly sync, and idempotent upsert. | P3 | Greenfield |
| P4: Notes and Escalations | Build POST /note triggered by escalation events. | P4 | Greenfield (AthenaService does not implement sendPatientNote) |
| P5: Billing Real-Time Charge Posting | Build POST /procedure with CPT code mapping and parallel-run decommission of batch reports. | P5 | Greenfield |
| Clinical Model: PersonaEncounter | Create PersonaEncounter collection for CCDA encounter history. | P1a prerequisite | Missing — new collection |
| Clinical Model: PersonaMedication | Create PersonaMedication discrete collection for EHR-sourced medications with RxNorm. | P1a prerequisite | Partial — existing model is free text |
| Clinical Model: PersonaAllergy | Create PersonaAllergy discrete collection for EHR-sourced allergies with coded criticality. | P1a prerequisite | Partial — existing model is free text |
| Clinical Model: PersonaLab | Create PersonaLab collection or extend activity collection for EHR-sourced lab results. | P1a prerequisite | Partial — device-only today |
| Clinical Model: PersonaVital | Extend ActivitySource.SourceType or create PersonaVital collection for EHR-sourced vital history. | P1a prerequisite (extension path) | Partial — device-only today |
| Clinical Model: DiagnosisSource Enum Extension | Add ATHENA_CCDA and ATHENA_BULK_FHIR to DiagnosisSource enum. | P1a prerequisite | Missing — 1-2 hour change |

---

### Sub-Tickets

---

#### P0: Integration Platform Foundation / Event Bus Contract Definition

Description: Define the domain events the platform emits and the integration events the layer emits back; commit event schema (field names, types, versioning) for at least PatientEnrolled, CarePlanUpdated, CCDAReceived, and DocumentUploadSucceeded.
Acceptance criteria:
  - Event schema document is in repo with field-level definitions for all four named events.
  - Schema includes a version field and a defined versioning policy.
  - At least one event roundtrip (synthetic domain event in, integration event out) is logged in Integration Health Dashboard pipeline.
Complexity: M
Dependencies: Key Decision 7 (event substrate selection)
Decision points: Decision 7

---

#### P0: Integration Platform Foundation / ExponentialBackoffInterceptor Wiring

Description: Wire ExponentialBackoffInterceptor.java into the OkHttp client builders in AthenaApiService.java and RedoxApiService.java so that HTTP 429 responses trigger Retry-After-aware backoff in production EMR calls.
Acceptance criteria:
  - AthenaApiService OkHttp builder includes ExponentialBackoffInterceptor.
  - RedoxApiService OkHttp builder includes ExponentialBackoffInterceptor.
  - A test fires a synthetic 429 response at the OkHttp client and asserts the interceptor retries after the Retry-After header value before falling back to exponential backoff.
  - No change to ReactUtils.retryWithExponentialBackoff callsites required (layered, not replaced).
Complexity: S
Dependencies: None
Decision points: None

---

#### P0: Integration Platform Foundation / Mapping Config Schema

Description: Define the YAML or JSON mapping config schema for partner-keyed clinical data transforms; commit Griffin's v0 config file as the first instance.
Acceptance criteria:
  - Schema file (JSON Schema or equivalent) is in repo and validates the Griffin v0 config without errors.
  - Griffin v0 config contains at minimum: documentTypeId for CLINICALDOCUMENT, autoClose flag, and CCDA section mappings for encounters, medications, allergies, and diagnoses.
  - A schema validation unit test runs in CI and fails on a deliberately malformed config.
Complexity: L
Dependencies: Key Decision 8 (format selection)
Decision points: Decision 8

---

#### P0: Integration Platform Foundation / Auth Scaffolding Audit

Description: Document the two existing auth patterns (athena OAuth2 property injection, Redox RSA file-mount) and confirm the athena OAuth2 client in AthenaApiService.java can be reused for CCDA GET calls without new credentials infrastructure.
Acceptance criteria:
  - ADR (architecture decision record) or inline code comment documents the two patterns and confirms reuse scope.
  - A test confirms AthenaApiService.getToken() returns a valid Bearer token against the athena sandbox environment.
  - No new Kubernetes Secret is required for Phase 1a CCDA retrieval (assumption, needs verification against athena sandbox).
Complexity: S
Dependencies: athena preview environment provisioned
Decision points: None

---

#### P1a: CCDA Inbound / CCDA Retrieval Endpoint

Description: Implement GET /v1/{practiceid}/ccda/{patientid}/ccda in the integration layer using the existing AthenaApiService OAuth2 client; return the raw CDA XML for parsing.
Acceptance criteria:
  - GET call against athena sandbox returns a valid CDA XML document for a known test patient.
  - HTTP 429 responses trigger ExponentialBackoffInterceptor retry (depends on P0 wiring ticket).
  - Response is logged to Integration Health Dashboard with patient ID, practice ID, response code, and latency.
  - No CDA XML content is logged (PHI safeguard).
Complexity: S
Dependencies: P0 ExponentialBackoffInterceptor Wiring, P0 Auth Scaffolding Audit
Decision points: None

---

#### P1a: CCDA Inbound / CDA Parser Integration

Description: Integrate a CDA parser library (do not build from scratch) to parse CCDA XML into structured section objects for encounters, medications, problems, allergies, labs, and vitals.
Acceptance criteria:
  - Parser correctly extracts encounter section entries (date, type, provider) from a sample athena CCDA document.
  - Parser correctly extracts medication section entries (RxNorm code, SIG text, prescriber) from a sample athena CCDA document.
  - Parser correctly extracts allergy section entries (allergen code, reaction code, criticality) from a sample athena CCDA document.
  - Parser unit tests cover at least one document with a missing section (graceful null handling, no exception thrown).
  - No external library is added that requires a new security review beyond standard OSS vetting.
Complexity: M
Dependencies: CCDA Retrieval Endpoint
Decision points: None

---

#### P1a: CCDA Inbound / CCDA Entity Adapters

Description: Implement six CCDA adapters in the platform layer, one per clinical entity: encounter adapter, medication adapter, allergy adapter, diagnosis adapter, lab adapter, and vital adapter. Each adapter transforms parsed CCDA section objects into the corresponding Persona write calls using the mapping config schema defined in P0.
Acceptance criteria:
  - Each adapter has a unit test that takes a parsed CCDA section object and asserts the correct Brook entity fields are populated.
  - DiagnosisSource.ATHENA_CCDA is used for all diagnosis adapter writes (depends on DiagnosisSource enum extension ticket).
  - Adapters read from the Griffin v0 config file, not from hardcoded field names.
  - An adapter unit test asserts that an unrecognized CCDA section does not throw an exception but logs a warning.
Complexity: L
Dependencies: CDA Parser Integration, P0 Mapping Config Schema, DiagnosisSource Enum Extension, persistence decisions for all entities (Decision 1)
Decision points: Decisions 1, 2, 3



---

#### P1a: CCDA Inbound / POCAR On-Demand Trigger

Description: Add a new API endpoint in brook-backend that a nurse can invoke from brook-web-app to trigger a fresh CCDA pull for a specific patient; wire the brook-web-app UI action to call it.
Acceptance criteria:
  - POST /api/patients/{personaId}/ccda-refresh endpoint exists in brook-backend and returns 202 Accepted.
  - brook-web-app has a UI action (button or chart-open hook) that calls the endpoint for Griffin patients.
  - The endpoint is protected by care team authentication; patient-role tokens receive 403.
  - The last_pocar_opened_at signal in care-nexus is not used as an automatic trigger in v1 (manual nurse action only, per Phase 1a scope).
  - Integration Health Dashboard receives a log entry on each trigger invocation.
Complexity: M
Dependencies: CCDA Retrieval Endpoint, CCDA Entity Adapters
Decision points: None

---

#### P1a: CCDA Inbound / Idempotency for CCDA Ingest

Description: Implement idempotency key on {patientId}:{CCDA document timestamp} so that fetching the same CCDA twice does not overwrite data with identical values or create duplicate entity records.
Acceptance criteria:
  - Fetching the same CCDA document twice for the same patient results in exactly one set of entity writes (second fetch is a no-op).
  - The idempotency key is stored in EmrLog or an equivalent dedup store with a TTL or version-based eviction policy.
  - A test fires the CCDA ingest handler twice with the same document and asserts the entity counts in each target collection are unchanged after the second call.
Complexity: S
Dependencies: CCDA Entity Adapters
Decision points: None

---

#### P1b: Clinical Document Upload / Mapping Config Migration

Description: Replace hardcoded documentTypeId=440672 and documentsubclass="CLINICALDOCUMENT" in AthenaService.java with values read from the Griffin v0 mapping config file.
Acceptance criteria:
  - AthenaService.java contains no hardcoded documentTypeId value.
  - The //TODO comment at AthenaService.java:52 is removed.
  - A unit test asserts that changing the config value changes the documentTypeId sent in the POST request.
  - A test asserts that a missing config key throws a startup-time configuration exception, not a runtime NullPointerException.
Complexity: S
Dependencies: P0 Mapping Config Schema
Decision points: Decision 8, Decision 9

---

#### P1b: Clinical Document Upload / Event-Driven Trigger

Description: Replace the batch-scheduled GENERATE_BUNDLED_REPORT queue trigger with an event-driven trigger on CarePlanUpdated domain events, while keeping the monthly re-assertion job.
Acceptance criteria:
  - A CarePlanUpdated event published to the event substrate triggers a document upload within 5 minutes (or within the defined SLA).
  - The monthly re-assertion job continues to run independently of event-driven triggers.
  - EmrLog dedup prevents double-upload if both a CarePlanUpdated event and the re-assertion job fire in the same month.
  - Integration Health Dashboard receives a log entry for each triggered upload attempt with outcome (success, retry, failure).
Complexity: M
Dependencies: P0 Event Bus Contract Definition, Key Decision 7 (event substrate)
Decision points: Decision 7, Decision 9

---

#### P1b: Clinical Document Upload / Parallel-Run Validation

Description: Run the new mapping-config-driven event-driven path alongside the existing batch job for a defined validation window; compare outputs and disable the batch job after sign-off.
Acceptance criteria:
  - Both paths run simultaneously for at least one full monthly cycle without Griffin receiving duplicate documents (EmrLog dedup verified).
  - A comparison log shows document count, patient IDs, and document type for both paths; discrepancies are flagged.
  - The batch job's OutboundGate (GenericQueueProcessor:34-37) is disabled after validation sign-off without affecting the new event-driven path.
  - Partner Ops confirms no manual upload was required during the validation window.
Complexity: M
Dependencies: Event-Driven Trigger, Mapping Config Migration
Decision points: Decision 9

---

#### P2: Orders / Clinician Workflow Verification

Description: Confirm with a Brook nurse clinician whether Griffin v1 uses the postmodern order model (Brook PSM cultivates, physician signs post-hoc in athena task queue) or the classical model; document the answer as a binding scope decision.
Acceptance criteria:
  - A written summary of the clinician verification call is in the Linear ticket or linked spec.
  - The summary confirms or revises the postmodern-only assumption.
  - If both models are required, a scope change ticket is created before Phase 2 implementation begins.
Complexity: S
Dependencies: None (must complete in Phase 0 window)
Decision points: Decision 5

---

#### P2: Orders / Athena Order Ingest

Description: Implement the athena orders ingest path: Brook drafts order, physician signs in athena task queue, Brook receives signed-order signal, Brook activates patient.
Acceptance criteria:
  - An order signed by a test physician in athena preview triggers patient activation in Brook within the polling interval.
  - A duplicate signed-order signal does not activate the patient a second time (dedup verified).
  - Order ingest follows the Redox ORM precedent: webhook or polling endpoint, order queue, scheduled processor.
  - Integration Health Dashboard receives a log entry for each order event with patient ID, order ID, and outcome.
Complexity: XL
Dependencies: Clinician Workflow Verification, Andrew's dedup review (Decision 6), P0 Foundation complete
Decision points: Decisions 5, 6

---

#### Clinical Model: DiagnosisSource Enum Extension / Add ATHENA_CCDA and ATHENA_BULK_FHIR

Description: Add ATHENA_CCDA and ATHENA_BULK_FHIR values to DiagnosisSource.java in brook-backend.
Acceptance criteria:
  - DiagnosisSource enum contains ATHENA_CCDA and ATHENA_BULK_FHIR values.
  - Existing unit tests that enumerate DiagnosisSource values are updated to include the new values.
  - No existing DiagnosisSource.PAP, REDOX, MANUAL, MIGRATION, or OTHER usages are changed.
  - The enum is deployed to the integration environment before Phase 1a CCDA mapper integration tests run.
Complexity: S
Dependencies: None
Decision points: Decision 3

---

#### Clinical Model: PersonaEncounter / Create PersonaEncounter Collection

Description: Define and deploy a PersonaEncounter @Document class in brook-backend for storing CCDA-sourced clinical encounter history.
Acceptance criteria:
  - PersonaEncounter.java exists with at minimum: personaId, encounterDate, encounterType, visitNumber, attendingProvider, reasonCode (ICD-10), sourceType (ATHENA_CCDA), and sourceReferenceId fields.
  - A MongoDB index exists on (personaId, encounterDate).
  - A repository interface exists for PersonaEncounter with findByPersonaIdOrderByEncounterDateDesc.
  - A unit test inserts one PersonaEncounter document and retrieves it by personaId.
Complexity: M
Dependencies: Decision 1 (persistence pattern), Decision 6 is N/A for encounters
Decision points: Decision 1

---

#### Clinical Model: PersonaMedication / Create PersonaMedication Collection

Description: Define and deploy a PersonaMedication @Document class for CCDA-sourced medication list data with RxNorm coding, distinct from the existing care plan free-text medication section.
Acceptance criteria:
  - PersonaMedication.java exists with at minimum: personaId, rxNormCode, medicationName, dosageInstruction (structured), prescriber, authoredOn, status, sourceType (ATHENA_CCDA), and sourceReferenceId fields.
  - A MongoDB index exists on (personaId, rxNormCode).
  - The existing patient_care_plans.current_medications[] section is not modified by this ticket.
  - A unit test inserts one PersonaMedication document and retrieves it by personaId.
Complexity: M
Dependencies: Decision 1 (persistence pattern for medications)
Decision points: Decision 1

---

#### Clinical Model: PersonaAllergy / Create PersonaAllergy Collection

Description: Define and deploy a PersonaAllergy @Document class for CCDA-sourced allergy data with coded allergen, criticality, and reaction.
Acceptance criteria:
  - PersonaAllergy.java exists with at minimum: personaId, allergenCode (RxNorm or SNOMED), allergenDisplay, criticality (mild/moderate/severe/life-threatening), reactionCode, reactionDisplay, clinicalStatus, onsetDate, sourceType (ATHENA_CCDA), and sourceReferenceId fields.
  - A MongoDB index exists on (personaId, allergenCode).
  - The existing patient_care_plans.allergies[] section is not modified by this ticket.
  - A unit test inserts one PersonaAllergy document and retrieves it by personaId.
  - A unit test asserts that criticality is stored as a typed enum, not a free-text string.
Complexity: M
Dependencies: Decision 1 (persistence pattern for allergies)
Decision points: Decision 1

---

#### Clinical Model: PersonaVital or ActivitySource Extension / EHR Vital Signs Persistence

Description: Either extend ActivitySource.SourceType with ATHENA_CCDA (Option A) or create a new PersonaVital collection (Option B) for CCDA-sourced historical vital signs. Ticket scope is determined by Decision 4.
Acceptance criteria (Option A — extend activity):
  - ActivitySource.SourceType contains ATHENA_CCDA.
  - dbt billing models that filter or aggregate on ActivitySource are confirmed to exclude ATHENA_CCDA records from RPM billing calculations.
  - A unit test inserts an activity record with SourceType.ATHENA_CCDA and confirms it does not appear in a billing query test fixture.
Acceptance criteria (Option B — new collection):
  - PersonaVital.java exists with at minimum: personaId, loincCode, value, unit, effectiveDateTime, sourceType (ATHENA_CCDA), and sourceReferenceId fields.
  - A MongoDB index exists on (personaId, loincCode, effectiveDateTime).
  - A unit test inserts one PersonaVital document and retrieves it by personaId and loincCode.
Complexity: M (Option A) or L (Option B)
Dependencies: Decision 4
Decision points: Decision 4
