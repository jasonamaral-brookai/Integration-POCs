# Dev-Readiness Report: linear-project.md

**Reviewed by:** dev-ready-agent
**Date:** 2026-06-30
**Documents reviewed:**
- `spec/linear-project.md` (primary)
- `findings.md` (recon ground truth)
- `spec/data-model-gaps.md` (entity status ground truth)

---

## Verdict: READY WITH CONDITIONS

The spec is unusually well-grounded for a draft — it cites file paths, line numbers, PR numbers, and open decisions explicitly rather than hiding them. Engineering can read this document and understand what exists versus what is greenfield. However, seven conditions must be resolved before the bulk of P1a and P1b implementation can begin. P0 Foundation tickets can start immediately, as can the Clinical Model sub-tickets that are persistence-decision-independent.

---

## Precision Issues

**1. "Handle" used without a defined action — P2 Orders ticket**
> "Brook receives signed-order signal, Brook activates patient."

"Activates patient" is undefined. Does activation mean: enrolling in a care pathway, sending a welcome message, enabling device monitoring, or some combination? The Redox ORM precedent (`RedoxService.java:192-199`) shows a 10-minute processor that queues and processes — but what "patient activation" means as a downstream outcome is not stated. Suggested fix: enumerate the activation steps (e.g., "set enrollment status to ACTIVE, trigger care pathway assignment, send welcome notification via CIO").

---

**2. "Integrate" without defined action — P0 Mapping Config Schema ticket**
> "commit Griffin's v0 config file as the first instance"

The acceptance criterion requires `documentTypeId`, `autoClose`, and CCDA section mappings, but "section mappings" is undefined. Which CCDA sections are required in v0? Which fields within each section? The spec lists encounters, medications, allergies, and diagnoses as four sections but does not define what a section mapping must contain (field name, FHIR code, target Brook field, transform function). Suggested fix: require the Griffin v0 config to have at least one complete end-to-end mapping example (e.g., CCDA Encounter.date → PersonaEncounter.encounterDate) so the schema definition is validated against a real use case before CI enforcement.

---

**3. Vague SLA threshold — P1b Event-Driven Trigger acceptance criterion**
> "triggers a document upload within 5 minutes (or within the defined SLA)"

"The defined SLA" is not defined anywhere in the spec. The parenthetical suggests this is a placeholder. Suggested fix: either commit to the 5-minute threshold or replace the criterion with "triggers a document upload within the SLA defined in Key Decision 7's substrate selection documentation." The current phrasing will cause the CI test to be written against an arbitrary threshold.

---

**4. "Equivalent dedup store" is undefined — P1a Idempotency ticket**
> "The idempotency key is stored in EmrLog or an equivalent dedup store"

If "equivalent dedup store" is in scope, engineering needs to know what qualifies. The current EmrLog key scheme (`personaId, providerOfficeId, month, filename, type`) is documented in `findings.md`; the extension needed for CCDA inbound is not. Suggested fix: commit to EmrLog as the dedup store for Phase 1a and define the compound key explicitly: `(personaId, practiceId, ccdaDocumentTimestamp, sectionType)`.

---

**5. Undefined referent — P1a POCAR Trigger, "Griffin patients"**
> "brook-web-app has a UI action (button or chart-open hook) that calls the endpoint for Griffin patients."

"Griffin patients" is not defined in the spec. There is no explanation of how the UI determines whether a patient is a Griffin patient (by `providerOfficeId`, by a feature flag, by an `OutboundGate`, or by some other discriminator). Suggested fix: define the gate condition explicitly, e.g., "the endpoint is called only when `ProviderOffice.emrDetails.partnerType == ATHENA` and the nurse's session is associated with a Griffin practice."

---

**6. "Store pattern established in P1b" — P4 Notes and Escalations**
> "Reuses the store pattern established in P1b."

"Store pattern" is ambiguous — does this mean `EmrLog` dedup, the `OutboundGate` check, the event-driven trigger, or all three? The notes use case is structurally different from document upload: notes are triggered by escalation domain events, not care plan updates, and the payload is a plain text note rather than a PDF. Suggested fix: enumerate which specific patterns from P1b apply to P4 (e.g., "reuses EmrLog for outbound dedup; reuses OutboundGate check at `GenericQueueProcessor:34-37`; does NOT reuse GENERATE_BUNDLED_REPORT queue action").

---

**7. Vague metric — Success Metrics table**
> "CCDA ingest latency ... Target: TBD (target: under 10 seconds for on-demand pull; assumption, needs verification against athena API SLA)"

A TBD success metric in a spec cannot be used as an acceptance criterion or monitored in the Integration Health Dashboard. The spec acknowledges the uncertainty but leaves it unresolved. Suggested fix: define a provisional SLA (e.g., "under 10 seconds for on-demand pull, under 30 seconds including athena API response time") and mark it as provisional pending athena sandbox measurement in Phase 0.

---

## Completeness Gaps

**1. No nurse-facing error state defined for CCDA pull failure — P1a**
The spec defines the happy path (POCAR trigger → 202 Accepted → data in POCAR) but does not define what a nurse sees when the CCDA pull fails. Failure modes include: athena returns 404 (patient not found), athena returns 429 (rate limited), CDA parser throws on a malformed document, no matching persona for the returned MRN. `findings.md` confirms POCAR is `brook-web-app` and that the nurse manually triggers the pull — meaning failure is visible to the nurse. No ticket or acceptance criterion addresses this. Suggested addition: add a sub-ticket "P1a: CCDA Inbound / Error State Handling" defining the nurse-visible error states and the fallback message in POCAR for each failure mode.

---

**2. No partial CCDA handling defined — P1a CDA Parser Integration**
The CDA Parser ticket acceptance criterion covers "at least one document with a missing section (graceful null handling, no exception thrown)" but does not define what happens to the data that *was* parsed from a partially valid document. If an athena CCDA has a valid encounters section but a malformed medications section, does the ingest: (a) write encounters and skip medications, (b) reject the entire document, or (c) write encounters and write a parse-error record for medications? This is a clinical data completeness question that affects what nurses see. Suggested addition: add an acceptance criterion: "If one CCDA section fails to parse, successfully parsed sections are written and the failed section is logged to Integration Health Dashboard with the specific parse error; the nurse is not notified of a partial failure in v1."

---

**3. No allergy authority / merge semantics defined — P1a CCDA-to-Persona Entity Mappers**
`data-model-gaps.md` Open Questions explicitly calls out: "Does Brook's clinical team consider care team-entered allergy data authoritative, or should EHR-sourced data override/supplement it?" This question directly affects CCDA mapper behavior: should `PersonaAllergy` writes from CCDA overwrite existing `patient_care_plans.allergies` entries, or coexist? This is not addressed in any Key Decision or acceptance criterion. Suggested addition: add a Key Decision 11 or a requirement in the PersonaAllergy ticket specifying the authority model (e.g., "EHR-sourced allergies supplement but do not overwrite care team-entered allergies; source field discriminates origin").

---

**4. ETL propagation for new entities not addressed — P1a and P3**
`data-model-gaps.md` Open Questions calls out: "Does PersonaTransformer in ETL-service propagate `persona.diagnoses[]` changes to Snowflake/Customer.io downstream?" and notes this was not found. The spec adds six new entity collections (PersonaEncounter, PersonaMedication, PersonaAllergy, PersonaLab, PersonaVital, and writes to PersonaDiagnosis). None of the sub-tickets or acceptance criteria address whether downstream consumers (Snowflake dbt models, Customer.io via ETL-service) will see these entities. If they do not, CCDA-sourced clinical data will be invisible to analytics and care automation. Suggested addition: add an acceptance criterion to each Clinical Model ticket: "PersonaTransformer in ETL-service is confirmed to include [entity] in its change stream, or a follow-on ETL ticket is created before Phase 1a exit."

---

**5. P3 Bulk FHIR three-step async pattern has no acceptance criteria — P3**
P3 is the only phase with no sub-tickets and no acceptance criteria. The description mentions "initiate export, poll status, retrieve manifest, download NDJSON" and "idempotent upsert" and "MRN + provider ID + Brook patient ID + DOB matching" — but none of these are expressed as testable criteria. The matching logic (four-field compound match) is particularly important and likely to be the source of dedup bugs (analogous to the Redox AAR-247 lead-provider bug). Suggested addition: break P3 into at minimum three sub-tickets (Export Initiation, Polling/Retrieval, Idempotent Upsert) each with acceptance criteria covering the async polling loop, NDJSON parsing, and the four-field matching strategy.

---

**6. P4 and P5 have no sub-tickets and no acceptance criteria**
P4 (Notes and Escalations) and P5 (Billing) are described at the epic level only. Both are greenfield. An engineer picking up P4 knows the target API (`POST /note`) but has no definition of: which escalation domain events trigger the note, what the note payload format is, how `AthenaApi.sendNote()` should be implemented, or how EmrLog dedup applies. P5 has no CPT code mapping specification, no definition of which programs map to which CPT codes, and no acceptance criteria for the parallel-run decommission of the batch report. Suggested addition: add sub-tickets for P4 (Note Trigger Event Definition, Note Payload Mapper, AthenaApi sendNote Implementation) and P5 (CPT Code Mapping Config, Charge Posting Event Handler, Parallel Run Decommission) with acceptance criteria before P4/P5 enter active development.

---

**7. athena order polling design is absent — P2**
The P2 Orders ticket says "Redox ORM ingest is the correct precedent pattern" (webhook or polling endpoint, order queue, scheduled processor) but does not commit to either webhook or polling for athena. Athena's signed-order signal delivery mechanism (push webhook vs. pull polling) determines the entire ingest architecture. The Redox pattern uses an inbound webhook (`/open/redox/webhook`); athena may use a different mechanism. Suggested addition: add a sub-ticket "P2: Orders / Athena Signed-Order Signal Verification" to confirm with athena documentation or sandbox testing whether signed-order notification is webhook-push or polling-required, before the ingest architecture is committed.

---

**8. `GenericClinicalObservation` base model gap not addressed — P1a**
`data-model-gaps.md` Section 8 identifies a "Generic Clinical Observation Pattern" as MISSING and recommends deciding in Phase 1a whether PersonaLab and PersonaVital share a common abstract base class. This decision affects the class design for both collections and the mapper implementation. The spec does not acknowledge this question, and neither the PersonaLab nor PersonaVital Clinical Model tickets address whether a shared base model is required. Suggested addition: add a note to the PersonaVital/PersonaLab tickets: "Engineering must confirm before implementation begins whether PersonaLab and PersonaVital share a common ClinicalObservation base class or are entirely separate documents. Decision gate: data-model-gaps.md Section 8."

---

## Consistency Issues

**1. Entity term inconsistency: "PersonaDiagnosis" vs. "Diagnosis" vs. "diagnoses[]"**
The spec uses three different referents for the same concept:
- "PersonaDiagnosis" (entity table, Workstream 2 header, mapper ticket description)
- "`persona.diagnoses[]`" (Key Decision 1, Key Decision 2, entity table "Brook Storage Today" column)
- "Diagnosis" (Success Metrics table: "7 (Diagnosis, Encounter, Medication...)")

All three refer to the same storage target. The Success Metrics table should read "PersonaDiagnosis" to be consistent with the rest of the spec. The Key Decisions should consistently say "writes to `persona.diagnoses[]` via `PersonaDiagnosis`" to make the relationship between the entity name and the storage path explicit.

---

**2. PersonaLab persistence path inconsistency between spec and data-model-gaps.md**
The spec's entity table (Workstream 2) says PersonaLab status is "PARTIAL — device only, no EHR labs" and Key Decision 1 groups it under Option A (new discrete collection). However, data-model-gaps.md Section 6 Recommended Sequence says "Phase 1a — create `PersonaLab` collection" as its primary recommendation, while the spec's Clinical Model epic for PersonaLab says "Create PersonaLab collection or extend activity collection for EHR-sourced lab results" — leaving the decision open in the epic title itself. The epic's label should not encode a decision that is still open; it creates ambiguity about what the epic delivers. Suggested fix: rename the epic to "Clinical Model: PersonaLab Persistence" and note that Decision 1 determines the implementation approach.

---

**3. Phase numbering inconsistency: P1a prerequisites labeled as "P1a prerequisite" but not as P0**
The Clinical Model tickets (PersonaEncounter, PersonaMedication, PersonaAllergy, PersonaLab, PersonaVital, DiagnosisSource Enum) are labeled "P1a prerequisite" in the epic table. The Workstream 2 intro says "P1a minimum model changes must land before CCDA parser implementation begins." However, these tickets are not assigned to any phase — they float outside the P0–P5 numbering. If engineers slot work by phase, these tickets may be deprioritized or started concurrently with P1a rather than before it. Suggested fix: assign Clinical Model prerequisite tickets explicitly to a "P0.5" or "P1a-prereq" phase label in Linear, or label them "Phase 0 exit criterion — required before P1a begins."

---

**4. Owner field blank — project metadata table**
The project metadata table at the top of the spec has `Owner: ` with no value. Key Decisions 5 and 6 have "(Jason to fill)" notes. These are not consistency issues per se, but they mean ownership is undefined at the spec level and the decisions have no assigned DRI. Two Key Decisions that are listed as blockers for P2 have no owner. Suggested fix: fill `Owner` with the DRI before engineering handoff; resolve Decision 5 and 6 owner attribution.

---

**5. "Link TBD" in project header**
`Linear: [link TBD]` and `Testing Plan: [link TBD]` — these are placeholder fields, not a consistency issue in text, but they indicate the spec has not been imported to Linear yet. An engineering team cannot track work against a spec with no Linear link. This must be resolved before handoff.

---

**6. Key Decision 1 does not cover PersonaAllergy or PersonaLab separately**
Key Decision 1 ("Clinical data persistence pattern per entity") covers Encounter, Medication, Allergy, Lab, and Vital in aggregate. However, the options (A, B, C) treat all five entities uniformly. Data-model-gaps.md makes clear that the persistence question differs per entity: Allergy has a clinical safety argument for discrete storage regardless of the medication decision; PersonaLab has a billing pollution argument distinct from PersonaVital. The decision should be broken into entity-specific sub-questions, or Option C (hybrid) should explicitly enumerate which entities go to which path. Suggested fix: update Key Decision 1 to enumerate the per-entity recommendation from data-model-gaps.md as a starting point for the decision meeting, rather than treating all five entities identically.

---

## Acceptance Criteria Gaps

**1. P0: Auth Scaffolding Audit — criterion is partially untestable**
> "No new Kubernetes Secret is required for Phase 1a CCDA retrieval (assumption, needs verification against athena sandbox)"

A negative assertion ("no new secret required") that is marked as an assumption cannot be an acceptance criterion — it cannot be verified as pass/fail in CI. Suggested testable replacement: "AthenaApiService.getToken() returns a valid Bearer token against the athena sandbox for the CCDA GET scope. If a new Kubernetes Secret is required, a follow-on infrastructure ticket is created before P1a implementation begins."

---

**2. P0: Event Bus Contract Definition — "at least one event roundtrip" criterion is too broad**
> "At least one event roundtrip (synthetic domain event in, integration event out) is logged in Integration Health Dashboard pipeline."

"Logged" is not testable — it does not specify what log fields are required, what the dashboard threshold is, or what constitutes a successful roundtrip vs. a failed one. Suggested testable replacement: "A synthetic `PatientEnrolled` event published to the selected substrate produces a corresponding `CCDAReceived` integration event within 30 seconds; both events appear in the Integration Health Dashboard with the correct patientId, timestamp, and outcome fields."

---

**3. P1a: CCDA-to-Persona Entity Mappers — Decision 1 dependency means AC cannot be fully written yet**
The acceptance criteria say "DiagnosisSource.ATHENA_CCDA is used for all diagnosis writes" but the persistence targets for Encounter, Medication, Allergy, Lab, and Vital are listed as pending Decision 1. This means the mapper ticket's AC is partially unwritable — the assertion "correct Brook entity fields are populated" cannot be specified until each entity's write target is confirmed. Engineering cannot write or test the mapper without knowing whether a PersonaMedication collection or an extended CurrentMedications document is the target. This is a blocker, not just a gap. Suggested resolution: resolve Decision 1 before the mapper ticket is assigned to a sprint; update AC to name specific target fields after the decision is made.

---

**4. P1b: Parallel-Run Validation — "Partner Ops confirms" is not a CI-testable criterion**
> "Partner Ops confirms no manual upload was required during the validation window."

Manual confirmation from a non-engineering team is not a testable acceptance criterion in the software sense. It also introduces a dependency on Partner Ops availability that is not tracked in the spec. Suggested testable replacement: "Integration Health Dashboard shows zero Partner Ops-initiated uploads (document_source = MANUAL) for Griffin patients during the validation window. A Partner Ops sign-off record is attached to the Linear ticket as a linked document."

---

**5. P2: Athena Order Ingest — "within the polling interval" is undefined**
> "An order signed by a test physician in athena preview triggers patient activation in Brook within the polling interval."

The polling interval has not been defined anywhere in the spec. The Redox precedent uses a 10-minute processor; athena may use a different cadence. If the polling interval is not specified, the criterion cannot be tested. Suggested testable replacement: "An order signed by a test physician in athena preview triggers patient activation in Brook within [N] minutes of signing, where N is defined by the Clinician Workflow Verification sub-ticket outcome and documented in the event-driven trigger design."

---

**6. P0: Mapping Config Schema — "schema validation unit test runs in CI" criterion is incomplete**
> "A schema validation unit test runs in CI and fails on a deliberately malformed config."

The criterion does not specify which CI environment (integration, staging, production) or which test framework. More importantly, "deliberately malformed config" is not defined — is a missing required key malformed? A wrong type? An unrecognized section name? The CI test cannot be written from this criterion. Suggested testable replacement: "A JUnit test provides a config file with (a) a missing required `documentTypeId` key and (b) an unrecognized CCDA section name, and asserts that schema validation throws a `ConfigValidationException` for each case."

---

**7. Clinical Model: PersonaEncounter — no display-path acceptance criterion**
The PersonaEncounter ticket creates the collection and repository but contains no criterion verifying that data written to PersonaEncounter is retrievable for display in the POCAR UI (the stated goal of Phase 1a). A collection that is written but never read by the UI does not eliminate dual-screening. Suggested addition: "A care team API call for `personaId` returns PersonaEncounter records sorted by encounterDate descending, and the POCAR chart view displays the most recent encounter date and type."

---

**8. P3: Bulk FHIR Patient Population Ingest — no acceptance criteria at all**
P3 has no sub-tickets and no acceptance criteria. This is a complete gap. P3 is described as "nightly cadence; idempotent upsert into Brook patient model; MRN + provider ID + Brook patient ID + DOB matching" but none of these are testable as written. A four-field identity matching strategy with no acceptance criterion is a dedup bug waiting to be discovered post-deploy. Suggested addition: create sub-tickets for P3 with AC covering at minimum: (a) the polling loop terminates on export completion or timeout, (b) a patient matched by all four fields is upserted exactly once across repeated nightly runs, (c) a patient matched by MRN only (other fields differ) is flagged for manual review rather than auto-merged.

---

**9. P4 and P5: No sub-tickets, no acceptance criteria**
Both P4 and P5 exist only as epic descriptions. Neither has sub-tickets. P5 mentions a "parallel-run decommission" with no exit criterion defined. No ticket in P4 or P5 is testable. These phases cannot be estimated, assigned, or tracked against completion. Suggested addition: before P4/P5 enter sprint planning, create sub-tickets per the Completeness Gap #6 recommendation above.

---

## Items Blocking Engineering Handoff

The following conditions must be resolved before P1a and P1b implementation can begin. P0 Foundation and Clinical Model prerequisite tickets can start in parallel.

- **Blocker 1 (P1a): Key Decision 1 — Clinical data persistence pattern per entity.**
  The CCDA mapper cannot be implemented until persistence targets are defined for Encounter, Medication, Allergy, Lab, and Vital. Mapper ticket AC is explicitly unwritable until this decision is made. Owner: Backend, DNA. Action: convene a 60-minute architecture decision meeting; document the outcome as an ADR in the repo. Required before: P1a CCDA-to-Persona Entity Mappers ticket is assigned.

- **Blocker 2 (P1a): Key Decision 2 — PersonaDiagnosis vs. PersonaProblem duality.**
  CCDA problem list routing is undefined. Two separate write paths will be implemented by default if this is not resolved. Owner: Backend, DNA (flagged as most important question in data-model-gaps.md). Action: confirm whether `persona.diagnoses[]` is canonical and `PatientCarePlans.problemList` is deprecated-on-migration. Required before: CCDA problem list section mapper is written.

- **Blocker 3 (P0/P1a): Key Decision 7 — Event substrate selection.**
  Phase 0 Event Bus Contract Definition, Phase 1b Event-Driven Trigger, and all subsequent event-emitting phases are blocked until the substrate (SQS, MongoDB CDC, or Redis Streams) is selected. The "Integration Event Worker (Go)" referenced in the build plan was not found in any scanned repo. Owner: Backend, infra. Action: confirm whether the Go worker exists in a private repo or must be built; select substrate; document in ADR. Required before: Phase 0 Event Bus Contract Definition ticket is closed.

- **Blocker 4 (Phase 0): Key Decision 8 — Mapping config format.**
  Phase 0 exit criterion ("Griffin v0 config in repo") cannot be met until the format (YAML, JSON, or DSL) is decided. Owner: Backend tech lead. Action: decide in Phase 0 kickoff; write the schema definition. Required before: P0 Mapping Config Schema ticket is closed.

- **Blocker 5 (P2): Key Decision 5 — Orders workflow model.**
  P2 scope cannot lock without clinician verification of the postmodern-only vs. both-models assumption. Owner: Jason (clinician verification call). Action: schedule verification call; document outcome in Linear before P2 sub-tickets are created.

- **Blocker 6 (P1a): Allergy authority / merge semantics undefined.**
  CCDA mapper for PersonaAllergy cannot be written without knowing whether EHR data overrides or supplements care team-entered allergy data. This is a clinical workflow question. Owner: clinical lead / care team. Action: confirm with clinical team before PersonaAllergy mapper is implemented.

- **Blocker 7 (All phases): Linear link, Testing Plan link, and Project Owner are blank.**
  Engineering cannot track work, file bugs, or link PRs to a spec that has no Linear project link. Owner: Jason / project owner. Action: create the Linear project, fill the header fields, and link the Testing Plan before announcing engineering handoff.

---

## Items That Can Proceed

The following tickets are unblocked and can be started immediately:

- **P0: ExponentialBackoffInterceptor Wiring** — No decisions pending. Well-scoped, well-AC'd. 1-day task per findings.md.
- **P0: Auth Scaffolding Audit** — Blocked only on athena sandbox provisioning, not on any internal decision. Can begin once sandbox credentials are available.
- **Clinical Model: DiagnosisSource Enum Extension** — No decisions pending. `ATHENA_CCDA` and `ATHENA_BULK_FHIR` additions to `DiagnosisSource.java` are a 1-2 hour task and must ship before any P1a code can be tested end-to-end.
- **Clinical Model: PersonaEncounter** — Recommended as a discrete collection in both the spec and data-model-gaps.md regardless of Decision 1's outcome for other entities. Can proceed once Decision 1 confirms discrete collection for encounters (strongly implied by the clinical safety argument in data-model-gaps.md Section 2).
- **Clinical Model: PersonaAllergy** — Same as PersonaEncounter: the clinical safety argument for discrete allergy storage is independent of the broader persistence decision. Can proceed once allergy authority semantics are defined (Blocker 6, which is a clinical workflow question, not an architectural one).
- **P2: Orders / Clinician Workflow Verification** — This is itself a Phase 0 task. No engineering decisions required to schedule and run the clinician verification call.
- **P1b: Mapping Config Migration** — Once Key Decision 8 (format) is resolved, this is a well-scoped refactor of a known file (`AthenaService.java:52`) with clear acceptance criteria.
- **P0: Event Bus Contract Definition** — Can begin schema drafting work (defining event field names, versioning policy, event catalog) independently of substrate selection, though the roundtrip test criterion depends on Key Decision 7.
