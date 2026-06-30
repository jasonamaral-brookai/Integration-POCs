# Recon Summary — Top 5 Findings

> Generated: 2026-06-30
> Source: direct code scan of Brookai repos

---

## 1. The athena integration already exists — outbound only — and it is already brittle

The plan frames Phase 1b (clinical document upload) as a new build. In reality, `AthenaService.java` and `AthenaApi.java` are shipping code. Brook is already posting monthly PDF care plan bundles to athena's `/clinicaldocument` endpoint for Griffin today. The mechanism works: OAuth2 client credentials auth, Retrofit HTTP client, exponential retry, `EmrLog` dedup. The problem is that `documentTypeId=440672` and `documentsubclass="CLINICALDOCUMENT"` are hardcoded with `//TODO` comments, the trigger is batch-scheduled (not event-driven), and the idempotency key is filename-based instead of event-version-based. Phase 1b is not greenfield — it is a refactor of something live and fragile. That changes the risk profile: the mapping config schema and event-driven trigger need to be built alongside the existing code without breaking what Griffin is already receiving.

## 2. Redox lives entirely in brook-backend — not in py-pap — and is 82KB of inline application logic

The plan references a "PAP backend (Python)" where Redox ingest lives. This is wrong. Every line of Redox integration code is in `brook-backend` (Java): the webhook endpoint (`/open/redox/webhook`), the order queue, the 10-minute scheduled processor, all patient matching logic, all consent handling, all mapping from HL7-shaped data to Persona fields. `py-pap` has no Redox code at all. The 82KB `RedoxService.java` is exactly the anti-pattern the plan describes — "mapping logic and ingest semantics tangled into application code." Two bug fixes for AAR-247 (lead provider) and AAR-329 (consent on rematch) are open PRs as of the scan date, still in-flight. The plan treats these as historical seam bugs; they are active engineering work on PRs #1717 and #1758.

## 3. The "existing SQS-backed worker pattern" is not a single substrate — there are three

The plan states "the existing SQS-backed worker pattern is the substrate" and claims "we do not need to invent new infrastructure." Three different event substrates are running in production: (a) AWS SQS for device data (services-data → brook-backend via `QueueAlias.BROOK/BROOK_PLUS/NOTIFICATIONS`), (b) MongoDB Change Data Capture (CDC) for care-nexus, which watches the `persona` and related collections and writes derived `patient_features` to PostgreSQL, (c) Redis Streams (Valkey) for the data-platform CIO service that handles Customer.io and Zoom webhooks. The "Integration Event Worker (Go)" cited in the plan's architecture diagram was not found in any scanned repo or in the Brookai org listing. The athena integration layer needs to decide which substrate it actually uses — and that choice has infrastructure implications the plan has not made explicit.

## 4. CCDA inbound (Phase 1a) is the only phase with zero existing code — and the mapping problem is harder than the retrieval problem

The plan calls Phase 1a "proves the mapping architecture." That is accurate but undersells the CDA parsing work. There is no CDA/CCDA parser in any scanned repo — no library dependency, no XML schema references, no `ccda`, `ClinicalDocument`, or C-CDA text found anywhere. The athena CCDA endpoint returns a structured CDA XML document; mapping it to Persona fields (`currentMedications`, `allergies`, `diagnoses[]`, encounter history) requires a parser and a non-trivial field mapping. The existing `PatientCarePlans.java` has the right destination model (`currentMedications`, `allergies`, `problemList`) but there is no write path from an external document into those fields today. Additionally, the POCAR trigger described in the plan requires a new API endpoint in brook-backend AND a UI change in `brook-web-app` (the Angular care portal). The `last_pocar_opened_at` timestamp in care-nexus already propagates on chart open — that signal exists and could be the hook — but nothing downstream of it triggers a data fetch today.

## 5. The rate-limit-aware HTTP client exists but is disconnected from all production EMR calls

The plan lists "base HTTP client with rate-limit handling, exponential backoff, retry, idempotency-key generation" as Phase 0 deliverables — implying they need to be built. `ExponentialBackoffInterceptor.java` already implements HTTP 429 detection with `Retry-After` header parsing and exponential backoff at the OkHttp interceptor layer. `ReactUtils.retryWithExponentialBackoff()` implements RxJava3-layer retry. Both exist in `brook-backend`. Neither is wired into the production `AthenaApiService` or `RedoxApiService` OkHttp client builders. The athena client has 60-second connect timeout and 3-minute read/write timeouts but no 429 handling. The Redox client has no custom timeouts at all. Phase 0 for the HTTP client is a wiring task — add `ExponentialBackoffInterceptor` to the OkHttp builder in both service init methods — not a build task. This should take hours, not days.
