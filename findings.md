# Recon Findings

> Generated: 2026-06-30
> Repos scanned: brook-backend, fonzie (specs/docs only), care-nexus, services-data, ETL-service, data-platform, brookhealthcompanion-reactnative, py-pap
> Method: direct gh repo clone --depth=1 + grep/find + targeted file reads

---

## Foundation (Phase 0)

**Plan says:** Build a partner-agnostic platform with event bus contracts, auth/secrets layer, base HTTP client with rate-limit/retry/idempotency, mapping config schema (YAML/JSON, partner-keyed), observability. The "existing SQS-backed worker pattern is the substrate."

**Code shows:**

### Event bus substrate

The plan's description of "SQS-backed event workers" is partially correct but incomplete. The actual topology is:

- **services-data** uses `health.brook.devicebusdata.model.queue.QueueAlias` with aliases `BROOK`, `BROOK_PLUS`, `NOTIFICATIONS`. Device readings from Withings/Fitbit/Cellular flow through SQS via `SQSSender.java`. File: `/tmp/services-data/src/main/java/health/brook/servicesdata/common/SQSSender.java`.
- **brook-backend** has a `DataBusScheduler` that consumes from `QueueAlias.BROOK` and a `GenericQueueProcessor` (Spring Integration `@ServiceActivator`) that processes: `GENERATE_BULK_REGISTER_ORDER_FORMS`, `EMR_ACTIVITY_EXPORT`, `GENERATE_BUNDLED_REPORT`, `VERIFY_BUNDLED_REPORT`, `GENERATE_PROVIDER_REPORT_DATA`. File: `/tmp/brook-backend/src/main/java/ai/brook/channels/queue/GenericQueueProcessor.java`.
- **care-nexus** does NOT use SQS at all. It runs a MongoDB Change Data Capture (CDC) consumer — a single Go service watching MongoDB change streams and writing derived `patient_features` to PostgreSQL. File: `/tmp/care-nexus/services/cdc-consumer/internal/config/config.go`.
- **data-platform CIO service** uses Redis Streams (Valkey) for event queuing between webhook receipt and processing — not SQS. File: `/tmp/data-platform/services/cio/queue/manager.go`.
- The "Integration Event Worker (Go)" and "Integration Past Event Worker (Go)" referenced in the plan are NOT found as source-level repos. Not in data-platform, not in the Brookai org list.

**Gap:** The plan's "existing SQS-backed worker pattern" applies only to device data. The care-coordination layer runs MongoDB CDC; the data-platform integration service runs Redis Streams. Three different event substrates are in production. The athena integration layer cannot assume a single consistent SQS topology.

---

### Auth/secrets pattern

**Plan says:** Kubernetes Secret, encrypted at rest.

**Code shows:** Two distinct patterns already in production:

1. **Athena (OAuth2 client credentials):** `athena.client-id` and `athena.client-secret` injected via Spring `@Value`. Auth flow: Basic auth for token endpoint, then Bearer token for API calls. File: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/athena/api/AthenaApiService.java:40-43, 110`.

2. **Redox (RSA private key / JWT client assertion):** `redox.private-key-path` points to a file path on disk. Private key is read from filesystem at init time and used to sign RS384 JWT assertions. File: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/redox/api/RedoxApiService.java:53-56, 115-135`. This is a filesystem-mounted PEM key, consistent with a K8s Secret volume mount.

**Gap:** The plan treats "Kubernetes Secret" as one uniform pattern. Reality: Redox uses a mounted file path; athena uses Spring property injection. A new athena CCDA retrieval path can reuse the existing `AthenaApiService` OAuth2 client — no new auth infrastructure needed for Phase 1a or 1b.

---

### Base HTTP client with retry/rate-limit handling

**Plan says:** Needs to be built as part of Phase 0.

**Code shows:** Already exists, partially. `ExponentialBackoffInterceptor.java` handles HTTP 429 with `Retry-After` header parsing, exponential backoff, configurable max retries. File: `/tmp/brook-backend/src/main/java/ai/brook/utils/ExponentialBackoffInterceptor.java`. `ReactUtils.retryWithExponentialBackoff(maxRetries, initialDelaySeconds)` provides RxJava3-layer retry. File: `/tmp/brook-backend/src/main/java/ai/brook/utils/ReactUtils.java`.

**However:** `ExponentialBackoffInterceptor` exists as a class but is NOT wired into either `AthenaApiService` or `RedoxApiService` OkHttp client builders. Both use `ReactUtils.retryWithExponentialBackoff(3, 2)` which retries on any exception but does NOT parse `Retry-After` headers. The rate-limit-aware interceptor is implemented but not connected.

**Gap:** Phase 0 needs to wire in `ExponentialBackoffInterceptor`, not build from scratch. This is a 1-day task, not a week.

---

### Idempotency

**Plan says:** First-class concern; idempotency keys on every push.

**Code shows:** Outbound idempotency implemented via `EmrLog` (MongoDB collection `redox_log`) with unique compound index on `(provider_office_id, persona_id, file_name, type)`. `AthenaService.sendBundleReport()` checks existence before sending. File: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/model/EmrLog.java` and `AthenaService.java:57-70`.

**Gap:** Current idempotency key for athena is `(personaId, providerOfficeId, month-in-filename, documentType)` — month-based, not event-version-based. The plan's proposed `{entity}:{event}:{version}` key is more precise. Existing mechanism works for Phase 1b but will need extension for CCDA inbound (no existing key pattern).

---

### Mapping config schema

**Plan says:** Must be config, not hardcoded; Griffin's mapping becomes the first instance. "The long-term play is configuration over code."

**Code shows:** No mapping config schema (YAML, JSON, DSL) of any kind found in any scanned repo. Partner config for athena and Redox lives as embedded Java model fields stored in `ProviderOffice.emrDetails` in MongoDB: `Athena.java` (practiceId, departmentId) and `RedoxSources.java` (orders, notes, flowSheets, primary). Files: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/provideroffice/model/Athena.java` and `RedoxSources.java`. All transform logic for Redox ingest is hardcoded in `RedoxService.java` (82.7KB file with all mapping logic inline).

**Gap:** Zero existing implementation of mapping-as-config. This is the anti-pattern the plan wants to replace. Building the schema is genuine greenfield.

---

## CCDA Inbound (Phase 1a)

**Plan says:** GET `/v1/{practiceid}/ccda/{patientid}/ccda`; CDA parser library; mapping config extracts encounters, medications, problems, allergies; POCAR trigger UI (nurse clicks, fresh pull on demand).

**Code shows:**

- The athena integration implements only OUTBOUND: POST `/v1/{practice_id}/patients/{patient_id}/documents/clinicaldocument`. File: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/athena/api/AthenaApi.java:20-26`.
- No CCDA GET endpoint implemented anywhere in any scanned repo.
- No CDA parser library dependency found. No references to `ccda`, `C-CDA`, `ClinicalDocument` (HL7/CDA sense), or continuity-of-care XML in any Java/Go/Python source file.
- `AthenaApiService` has a functional OAuth2 client that can be reused for GET calls.
- `AthenaService` has only `sendBundleReport()` and `checkBundleReport()` — both outbound only.

**Gap:** Phase 1a (CCDA inbound) is fully greenfield. Reusable: athena OAuth2 client only. No parser, no retrieval endpoint, no POCAR trigger. This is the largest Phase 0/1 greenfield item.

---

## Clinical Document Upload (Phase 1b)

**Plan says:** POST `/clinicaldocument` triggered by `CarePlanUpdated` domain events; `documenttype` and `autoclose` driven by mapping config; 192+ Griffin care plans/month.

**Code shows:** Partially implemented and deployed:

- `AthenaService.sendBundleReport()` posts to the correct endpoint with `documentSubclass="CLINICALDOCUMENT"`, `autoClose=true`, `documentTypeId=440672` (hardcoded with `//TODO: make this configurable or dynamic when needed`). File: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/athena/AthenaService.java:52, 65`.
- Trigger: not via a `CarePlanUpdated` domain event — appears to be batch-scheduled (monthly report generation via `GenericQueueProcessor` with `GENERATE_BUNDLED_REPORT` action). Event-driven trigger does not exist.
- Idempotency: `EmrLog` dedup on `(personaId, providerOfficeId, month, type)`.
- `OutboundGate` gates the `BUNDLED_REPORT` action separately from `ATHENA`. File: `/tmp/brook-backend/src/main/java/ai/brook/channels/queue/GenericQueueProcessor.java:34-37`.

**Gap:** `documentTypeId=440672` and `documentsubclass` are hardcoded — exactly what mapping config is supposed to fix. No event-driven trigger; current path is scheduled batch. The plan's per-patient/per-month audit log is partially present via `EmrLog`. Implementation is closer to done than the plan implies — it is live for Griffin today, but brittle.

---

## Orders (Phase 2)

**Plan says:** Redox ORM ingest is the existing pattern; AAR-238/247/257/263/265/329/302 are seam bugs from mapping tangled into application code.

**Code shows:**

- Redox ORM ingest lives entirely in `brook-backend`. Webhook at `/open/redox/webhook`, verification token from `${redox.endpoint-verification-token}`. File: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/emr/redox/RedoxController.java`.
- Orders queue to `RedoxOrderQueueItem` collection; processed every 10 minutes by `emrOrderQueueProcess()`. File: `RedoxService.java:192-199`.
- **AAR-247** (lead provider not written): Code comments present, fix in-progress on `feature/AAR-257-redox-orm-clinic-transfer` (PR #1717). File: `RedoxService.java` + spec `/tmp/fonzie/specs/2026-06-10-redox-orm-ingestion-identity-resolution/plan.md`.
- **AAR-257** (patientProviderOfficeId not updated on cross-clinic rematch): Code comments present, fix in same PR. Routes cross-clinic re-matches through `transferPatientWithBilling()`.
- **AAR-329** (consent not honored on rematch): Code comments present, fix in-progress on `feature/AAR-329-redox-order-consent-guard` (PR #1758). Root cause: RPM consent auto-stamped even for CCM-only clinics (e.g., UMass Rheumatology), generating incorrect billing. Spec: `/tmp/fonzie/specs/2026-06-18-aar-329-redox-order-consent-guard/plan.md`.
- **AAR-238, AAR-263, AAR-265, AAR-302**: NOT found as code comments in any scanned file.

For athena: NO order ingest implemented. The plan's "physician signs in athena's task queue, Brook receives signed-order signal" path is entirely greenfield.

**Gap:** AAR-247, 257, 329 are actively in-flight fixes on open PRs — they are not closed. The athena orders path is greenfield. The Redox pattern (inbound webhook → queue → scheduled processor) is the correct precedent.

---

## Notes / Escalations (Phase 4)

**Plan says:** POST `/note` to athena; reuses store pattern from Phase 1b.

**Code shows:** Redox note sending (`sendPatientNote()`) posts base64-encoded PDF via Redox. `DocumentType` enum: `CLINICAL_NOTE`, `INTERACTION_NOTE`, `SUMMARY`, `SIMPLE_ESCALATION`, `ESCALATION_REPORT`. File: `RedoxService.java:147-190`. For athena: `AthenaApi` has only `sendDocument` — no `/note` endpoint method. `EmrService.sendPatientNote()` is declared in the interface but `AthenaService` does not implement it.

**Gap:** Athena note posting is not implemented. The plan's "light add" description is accurate in spirit but requires a new `AthenaApi.sendNote()` Retrofit method and corresponding service logic.

---

## Billing (Phase 5)

**Plan says:** POST `/procedure` for real-time CPT charge posting; parallel-run with existing batch.

**Code shows:** No athena billing endpoint (`/procedure`) implemented. Current billing path: monthly PDF bundle report posted as a clinical document (`AthenaService.sendBundleReport()`). The `OutboundGate` docs confirm `ATHENA` is a gated integration; any new charge-posting path needs separate gating. ENG-624 (Griffin Bariatrics billing API) is Done but uses the legacy batch pattern.

**Gap:** Phase 5 is fully greenfield. The "existing batch monthly bundled reports" referenced in the plan are the current `sendBundleReport()` implementation.

---

## Persona Model Location

**Plan says:** Brook canonical data model; Persona maps to FHIR Patient.

**Code shows (confirmed file paths):**

- `Persona.java`: `/tmp/brook-backend/src/main/java/ai/brook/data/persona/Persona.java` (collection: `persona`)
- `Profile.java`: `/tmp/brook-backend/src/main/java/ai/brook/data/persona/Profile.java` (embedded superclass)
- `ProviderDetails.java`: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/provideroffice/model/ProviderDetails.java` (embedded in Profile)
- `ProviderOffice.java`: `/tmp/brook-backend/src/main/java/ai/brook/api/rpm/provideroffice/model/ProviderOffice.java` (collection: `provider_office`)
- `RegisterService.java`: `/tmp/brook-backend/src/main/java/ai/brook/api/users/register/RegisterService.java` (previously listed as "not found" in gap doc — it exists)
- `PatientCarePlans.java`: `/tmp/brook-backend/src/main/java/ai/brook/api/caremanagement/model/PatientCarePlans.java` (collection: `patient_care_plans`; includes `currentMedications`, `allergies`, `problemList`)

Key integration fields for CCDA inbound mapping: `ProviderDetails.mrn`, `ProviderDetails.patientProviderOfficeId`, `ProviderDetails.leadProviderId`, `Persona.diagnoses[]` (PAI-184, merged 2026-05-20), `PatientCarePlans.currentMedications`, `PatientCarePlans.allergies`.

PAP → Persona lifecycle: PAP row is archived (`PapApi.archivePatient()`) once a persona is created. PAP and Mongo are sequential lifecycle stages, not synced copies. File: fonzie spec `redox-pap-interaction.md` referenced in `/tmp/fonzie/specs/2026-06-10-redox-orm-ingestion-identity-resolution/plan.md`.

---

## POCAR / Care Team UI

**Plan says:** POCAR trigger UI for nurse to pull CCDA on demand. "POCAR" is the care team patient chart UI.

**Code shows:**

- POCAR = the care portal web app (`brook-web-app`, Angular). Not a separate repo — it is the main care team UI. Not in `brookhealthcompanion-reactnative` (patient-facing only).
- `last_pocar_opened_at` is a column in the `patient_features` PostgreSQL table in care-nexus, written when a nurse opens a chart. File: `/tmp/care-nexus/services/cdc-consumer/internal/rules/next_eval.go:50` and reconciler test at line 457.
- `care-nexus` uses this timestamp for CCM interaction gap tracking (B2 bucket logic). It is not connected to any data retrieval trigger.
- No "CCDA pull on chart open" trigger exists anywhere.

**Gap:** POCAR is `brook-web-app`. The `last_pocar_opened_at` signal already propagates through care-nexus on chart open — this is the natural hook for a CCDA pull trigger, but no implementation exists. A new API endpoint in `brook-backend` and a UI action in `brook-web-app` are both required.

---

## PAP Backend

**Plan says:** Implies a "PAP backend (Python)" where Redox ingest lives.

**Code shows:** INCORRECT. Redox ingest lives in `brook-backend` (Java). `py-pap` (`Brookai/py-pap`) is the Patient Acquisition Platform — Python/Flask for patient lead management (CSV ingest, eligibility, notes). No Redox code found in `py-pap`. The `brook/integration/` directory in py-pap contains HTTP clients that call brook-backend, Billy, and register-engine. `register-engine` (`Brookai/register-engine`) is a separate patient registration middleware that brook-backend calls at `${register-engine.base-url}`.

**Gap:** The plan's reference to "PAP backend (Python) where Redox ingest lives" is factually wrong. Redox lives in brook-backend (Java). This distinction matters because any re-platforming of Redox ingest would require changes to brook-backend, not py-pap.

---

## Plan Assumptions I Could Not Verify

1. **"Integration Event Worker (Go)" and "Integration Past Event Worker (Go)"** referenced as existing infrastructure — not found as source repos in the Brookai org. May be in a private infra repo or renamed.

2. **"We do not need to invent new infrastructure" (SQS as universal substrate)** — three different event substrates are running in production (SQS for device data, MongoDB CDC for care-nexus, Redis Streams for data-platform CIO). The claim that one substrate covers all integration needs is not supported by the code.

3. **"AAR-263, AAR-265, AAR-238, AAR-302"** — not found as code comments in any scanned repo. Could be Linear-only tracking or fixed without annotation.

4. **OutboundGate coverage for new athena endpoints** — `ATHENA` is already a gated integration. Whether the single `ATHENA` enum value covers new endpoints (CCDA GET, orders, billing) or requires separate enum values needs clarification. File: fonzie/specs/outbound-gate-tldr.md.

5. **POCAR as a single named repo** — plan refers to "POCAR" as if it is a discrete service. It is the brand name for the care team UI in `brook-web-app`. CCDA trigger changes require `brook-web-app` (Angular) changes plus `brook-backend` API changes.

6. **Mapping config schema feasibility in Phase 0** — no schema infrastructure exists, no precedent. The plan lists "mapping config schema reviewed and Griffin's config v0 in repo" as a Phase 0 exit criterion. This is genuinely greenfield and likely the longest Phase 0 item.

7. **AAR-247 and AAR-329 are listed as "seam bugs"** — they are active open PRs as of the scan date (2026-06-30). They have not shipped. The plan treats them as historical evidence; they are ongoing active work.
