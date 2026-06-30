# Brook Integration Platform — athena + Griffin v1

> **Status:** Draft for engineering review
> **Owner:** Jason Amaral
> **Audience:** Brook engineering (all teams)
> **Date:** 2026-06-30
> **Companion doc (strategy / why):** [athena Integration — Vision & Product Brief](https://app.notion.com/p/358df47a35be81678b68de4135da16e6)
> **Reference artifacts:** Signed tech spec (May 12, 2025, narrow scope), expanded 11-use-case tech spec (in revision), Griffin_Interop_Future_State.pdf (architecture diagram), [Touchpoint with athena Marketplace contact (Rachel)](https://www.notion.so/athena-Brook-Touchpoint-352df47a35be80ce9825f8f699d6dd46)

---

## 1. Why this matters

**Brook is siloed at the operational tier.** Care happens inside Brook — care plans, escalations, vitals, encounters, billing artifacts get created here — but the clinical world outside (EHRs, labs, payers) is largely invisible to us. Nurses dual-screen into partner EHRs because we have no inbound clinical data mechanism at the point of care. Outbound flows exist, but they're partner-specific, manual-leaning, and brittle.

**The closest thing we have is Redox.** It works — UMass orders flow in via ORM, patients get matched, care gets initiated. But the bug pattern accumulating in the Partner Integration Linear project tells the story: we did inbound integration once before the platform existed, and the seams show. [AAR-238](https://linear.app/brook-health/issue/AAR-238) (demographics not refreshed on re-ingest), [AAR-247](https://linear.app/brook-health/issue/AAR-247) (lead provider not written for existing patients), [AAR-257](https://linear.app/brook-health/issue/AAR-257) (`patientProviderOfficeId` not updated on cross-clinic rematch), [AAR-263](https://linear.app/brook-health/issue/AAR-263) (name+DOB match not firing), [AAR-265](https://linear.app/brook-health/issue/AAR-265) (cross-clinic duplicate monitoring), [AAR-329](https://linear.app/brook-health/issue/AAR-329) (consent not honored on rematch), [AAR-302](https://linear.app/brook-health/issue/AAR-302) (eligibility rules drift). None of these are Redox's bugs. They're symptoms of mapping logic and ingest semantics tangled into application code instead of living in a defined layer.

**The athena work is where we build the platform.** A three-layer integration architecture — EHR-side connectivity, partner-configurable mapping, Brook canonical data model — gives us the connective tissue Brook has been missing. athena is the first EHR adapter on top of it. Griffin is the design partner that shapes v1. The marketplace is the distribution mechanism, not the goal.

**The framework is reusable.** Epic, Cerner, payers, labs, the next partner we haven't named — all become adapters on top of the same foundation. Redox itself becomes a candidate for re-platforming once the foundation is mature (separate decision, separate cycle). We are joining the clinical data network — and building it in a way that the network can keep growing through us.

The full strategic frame, including Griffin contract handling and the five pillars, lives in the [Vision & Product Brief](https://app.notion.com/p/358df47a35be81678b68de4135da16e6). This document is the engineering companion.

---

## 2. Architecture

> **Reading orientation:** Phase 0 (Section 3) builds **the platform** — partner-agnostic foundation. Phases 1a–5 build **athena's adapter on top of it** — the first EHR instance. This distinction is load-bearing: keep it in mind as you read the rest of the doc.

### 2.1 Three-layer pattern

**Integration layer** — EHR-specific connectivity. Two kinds of components:
- **Retrievers:** FHIR Bulk Export, CCDA pull, FHIR subscriptions when available.
- **Stores:** POST `/clinicaldocument`, POST `/note`, POST `/orders`, POST `/procedure`.

Speaks athena's wire protocols. Authoritative for athena-side semantics: rate limits, async polling, retries, idempotency keys, error taxonomy. Future EHRs (Epic, Cerner) get their own integration-layer components — same interface contract, different wire protocols.

**Mapping layer** — lives at the edge between integration and platform. EHR-shaped data in, Brook-shaped data out (and reverse for push). Per-partner.

**Must be expressed as configuration, not hardcoded transforms** — even in v1 where Griffin is the only configured partner. The long-term play is configuration over code: new EHR / new partner becomes a config file, not a sprint. The UI on top of this config comes later — [IDEA-40 (PAP Column Mapper)](https://linear.app/brook-health/issue/IDEA-40/pap-column-mapper-ops-tooling-for-onboarding-new-partner-csv-schemas) is the seed.

**v1 commitment:** the mapping config schema is defined and Griffin's mappings live in a config file, even though no UI sits on top of it yet. Defer the schema and we never come back to it.

**Platform** — owns Brook's canonical data model, persistence, and domain events (`PatientEnrolled`, `CarePlanUpdated`, `EscalationRaised`, `ChargePosted`, etc.). Existing services that fit this shape:

- Brook Backend (Java) — central hub
- [Integration Event Worker (Go)](https://app.notion.com/p/2f6df47a35be81728a1ff0b069d7ff8f) — real-time event processing
- Integration Past Event Worker (Go) — historical event processing
- Dataplatform (Go) — Snowflake operations

### 2.2 Event model

- **Platform emits domain events.** Integration layer subscribes for outbound flows.
- **Integration layer also emits events** for inbound flows: `BulkExportCompleted`, `CCDAReceived`, `DocumentUploadSucceeded`, `OrderSigned`.
- **Existing SQS-backed worker pattern** is the substrate. We do not need to invent new infrastructure.

### 2.3 Idempotency, replay, dedup

These are the silent killers of event-based EHR integrations, and they are exactly where the Redox seam-bugs live. First-class concerns, not code-time afterthoughts:

- **Idempotency keys** on every push: derived from `{Brook entity ID}:{event type}:{version}` or similar deterministic compound.
- **athena rate limits and retries** centralized in the base HTTP client.
- **Replay safety** — fire the same event twice → exactly one athena POST, exactly one logged delivery.
- **Orders dedup logic** is a specific instance of this broader concern; it's still TBD pending Andrew's review.

### 2.4 Canonical model alignment

Brook-shaped data should align with the FHIR R4 mapping defined in the [FHIR Datastore work](https://app.notion.com/p/2f6df47a35be810085c3cd8e3806ada9):

| Brook concept | FHIR resource |
|---|---|
| Persona | Patient |
| Care Plan | CarePlan |
| Vitals / Readings | Observation |
| Diagnoses | Condition |
| Provider Office | Organization |

The operational integration layer does **not** depend on AWS HealthLake landing (currently blocked on SCP approval). But speaking FHIR-shaped data upstream means operational and analytics paths share a vocabulary, and we don't have to retrofit later.

### 2.5 Application security (per signed tech spec)

- Key / secret storage: Kubernetes Secret, encrypted at rest.
- Access: Brook employees (RNs, LPNs, automated processes).
- Patient matching: MRN + provider ID + Brook patient ID + DOB.
- PHI safeguards: encryption + Snowflake masks.
- Error logging: yes, integrated with Integration Health Dashboard pipeline.

---

## 3. Phasing

> Phase 0 is the **platform**. Phases 1a–5 are **athena's adapter on top of it**, prioritized for Griffin's needs.

### Phase 0 — Foundation (the platform itself)

**Everything depends on this. This is the work that, in hindsight, we wish we'd had before Redox.**

**Scope:**
- Event bus contracts and schemas (domain events the platform emits; integration events the layer emits back).
- Integration-layer scaffolding:
  - Auth and secrets management (athena Kubernetes Secret pattern, generalizable to other EHRs).
  - Base HTTP client with rate-limit handling, exponential backoff, retry, idempotency-key generation.
  - Structured logging into the Integration Health Dashboard pipeline ([IDEA-36](https://linear.app/brook-health/issue/IDEA-36/integration-monitoring-prototype-centralized-partner-integration), [Integration PX project](https://linear.app/brook-health/project/integration-px-partner-integration-health-dashboard-01ede53f4eb3)).
- Mapping config schema (YAML or JSON, partner-keyed). Griffin's config file becomes the first instance.
- Observability — Datadog dashboards per pillar; error taxonomy aligned with the Integration Health Dashboard 9-category model.
- **Parallel discovery (not blocking eng scope but blocking Phase 2 lock):** clinician verification of the Orders workflow assumption ("Brook nurse drafts, physician signs in athena task queue").

**Exit criteria:**
- Single end-to-end "hello world": synthetic Brook domain event flows through integration layer to athena preview, response is logged, integration event fires back, idempotency on retry is verified.
- Mapping config schema reviewed and Griffin's config v0 in repo.
- Clinician verification call completed and orders assumption either confirmed or revised.

**Dependencies:** athena preview environment provisioned (3-4 day SLA after case submission).

**Linear status:** ❌ No ticket today — **needs new epic.**

---

### Phase 1a — CCDA inbound (clinical data sync)

> Proves the mapping architecture against a stable, certified athena interface.

**Why 1a:** CCDA is a document-shaped clinical snapshot with a stable certified endpoint. The mapping work — parse CDA document into Brook entities — exercises the mapping layer hard. Once this works, outbound pushes are simpler by comparison. Doing the easy push first would let the team believe the architecture works before it's been stress-tested by inbound transformation.

**Scope:**
- GET `/v1/{practiceid}/ccda/{patientid}/ccda` retrieval.
- CDA document parser (use existing library, do not roll our own).
- Mapping config extracts Brook entities from CDA: encounters, medications, problems, allergies.
- Ingestion into platform domain events.
- POCAR trigger UI — nurse opens patient chart → fresh CCDA pull on demand (reactive, not nightly batch).
- Idempotency on `{patient ID}:{CCDA timestamp}`.

**Exit criteria:**
- Nurse opening a Griffin patient chart in POCAR-preview retrieves a fresh CCDA from athena preview.
- Parsed encounter/medication data shows in POCAR UI.
- Dual-screening verification: nurse compares athena UI vs. POCAR vs. fetched CCDA — verified fields match.

**Out of scope for v1:** Discrete medication / order push *into* athena. Push direction needs more discovery and is not on the critical path.

**Linear status:** ❌ No ticket today — **needs new epic.** This is the biggest dual-screening reduction opportunity per the vision brief.

---

### Phase 1b — Clinical document upload (outbound store pattern)

> Validates the store side of the integration layer. Ships the ~7 hrs/mo Partner Ops manual upload savings.

**Scope:**
- POST `/v1/{practiceid}/patients/{patientid}/documents/clinicaldocument` triggered by `CarePlanUpdated` domain events and the monthly re-assertion job.
- Mapping config drives `documenttype` and `autoclose` (still awaiting athena client preference per signed spec).
- Error handling with exponential backoff retry.
- Persistent failures → Integration Health Dashboard alert.
- Per-patient, per-month audit log with timestamps.

**Exit criteria:**
- 192+ Griffin care plans/month flow automatically.
- No Partner Ops manual upload required.
- Missed uploads surface to Partner Ops within 1 hour via dashboard alert.
- Compliance posture: monthly re-assertion confirmed (Brook is required to send providers the care plan whenever it changes — outside counsel confirmed).

**Linear status:** ⚠️ Partial coverage — **[IDEA-21](https://linear.app/brook-health/issue/IDEA-21)** (platform-level care plan delivery automation) and **[IDEA-25](https://linear.app/brook-health/issue/IDEA-25)** (Griffin-specific). Both New Signal. Need to be promoted to active epic with sub-tickets under the new athena Marketplace project.

---

### Phase 2 — Orders (care initiation)

> Moved earlier in the sequence per Jason's direction. Discovery dependencies (Andrew's review, clinician verification) run in **parallel during Phase 0/1**. If those don't land, Phase 2 stalls and Phase 3 (Bulk FHIR) takes its slot.

**Scope:**
- Brook drafts orders based on eligibility identification.
- Physician signs in athena's task queue.
- Order pending state in Brook waits on signed-order signal from athena (CCDA pull on next cycle is acceptable; FHIR subscriptions would be better but are alpha-only).
- Dedup logic — **TBD pending Andrew's review.** This is a specific instance of the broader idempotency concern.
- Consent handling (per ANC, signed by Griffin during onboarding).
- Patient activation triggered by signed-order signal.

**Exit criteria:**
- End-to-end order signed by a Griffin physician via athena's task queue.
- Brook receives signed-order signal.
- Brook activates the patient.
- Dedup verified — duplicate orders don't double-activate.

**Why this needs Andrew's input most (per vision brief):** Griffin operates on the "postmodern" pathway — Brook PSMs cultivate the clinic relationship and the provider signs off post-hoc. The integration question isn't "will physicians place orders" — it's "how do we digitize the post-hoc signing pattern they already use?"

**Open question to resolve in Phase 0:** Single pattern (Brook drafts, physician signs in task queue) vs. supporting both classical and postmodern explicitly. Currently being explored with a Brook nurse clinician.

**Linear status:** ❌ No ticket today — **needs new epic.** [IDEA-15](https://linear.app/brook-health/issue/IDEA-15) was the closest umbrella, archived May 18.

**Blockers:**
- Andrew's review on dedup logic.
- Clinician verification of the workflow assumption.

---

### Phase 3 — Bulk FHIR patient population ingest

**Scope:**
- athena's three-step async pattern: initiate export → poll status → retrieve manifest → download NDJSON.
- Recurring cadence (start daily, tune from there).
- Eligibility filtering at ingest:
  - Global defaults (always excluded): deceased, inactive, under-18.
  - Partner-configurable toggles beyond that.
- Idempotent upsert into Brook patient model.
- Patient matching: MRN + provider ID + Brook patient ID + DOB.

**Exit criteria:**
- Full Griffin roster sync runs nightly.
- CSV/SFTP path runs in parallel for a defined window then retires.
- New clinic additions become config changes, not engineering tickets.
- Eliminates this class of work: [AAR-209](https://linear.app/brook-health/issue/AAR-209) (Southford UTF-8), [AAR-214](https://linear.app/brook-health/issue/AAR-214) (CSV byte-order bug), [PAI-15](https://linear.app/brook-health/issue/PAI-15) (manual Griffin clinic preprocessing), [ENG-468](https://linear.app/brook-health/issue/ENG-468) (manual rule copy).

**Why this matters:** Without a reliable population ingest, every new athena partner is a custom data plumbing project — exactly the failure mode the marketplace pattern is meant to escape.

**Linear status:** ⚠️ Partial coverage — **[IDEA-20](https://linear.app/brook-health/issue/IDEA-20)** (FHIR bulk export, Griffin called out in acceptance criteria). New Signal — needs promotion to active epic.

**Open question:** Filtering policy — what's universal vs. partner-configurable. Default: conservative globals + small set of toggles.

---

### Phase 4 — Notes / Escalations

> Light add. Reuses store pattern from Phase 1b — POST `/note` is structurally the same as POST `/clinicaldocument`.

**Scope:**
- POST `/note` triggered by escalation domain events.
- Physician acknowledgment via patient case closure (escalation path per the design decision in memory).
- Idempotency on escalation ID.
- **Signal-not-noise filtering at the mapping layer:** only clinically meaningful escalations surface to athena. This is the governing Brook design principle — only clinically meaningful information should surface to providers across care settings.

**Linear status:** ❌ No ticket today — **needs new epic.**

---

### Phase 5 — Billing: real-time charge posting

**Scope:**
- POCAR "ready for billing" state → `ChargePosted` event → POST `/procedure`.
- Correct CPT codes per program (99457/99458 RPM, 99490/99439 CCM, 99490 + addendums for APCM, etc.).
- Idempotent posting.
- Reconciliation logging.
- Parallel-run with existing batch monthly bundled reports for a defined window.

**Exit criteria:**
- Real-time charges post for Griffin without manual Brook staff entry.
- Parallel-run window concludes with finance team sign-off.
- Existing batch reports either retire or live in the EHR rather than as Brook-side artifacts.

**Honest caveat (per vision brief):** Griffin finance has workflows built around the current batch reports. Validation that real-time charge posting aligns with AR/reconciliation is required before scoping locks. Backup plan: parallel-run period.

**Linear status:** ❌ No ticket today — **needs new epic.** [ENG-624](https://linear.app/brook-health/issue/ENG-624/add-billing-api-for-griffin-bariatrics-and-weight-management-clinic) was Done for one clinic (Griffin Bariatrics) but is the legacy pattern, not the marketplace pattern.

**Support available:** athena IS consultant has billing component expertise (per Rachel's touchpoint). Worth tackling this pillar when the consultant window is active (70 days from assignment).

---

## 4. Testing / QA strategy

### 4.1 Three environments

- **athena sandbox** — open developer testing, used for endpoint-level verification.
- **athena preview** — Brook's own preview env. Takes 3-4 days to provision after case submission. IS consultant validates solution against this.
- **athena production** — post Solution Validation only. 5 business days of monitoring after go-live before marketplace publication.

Postman collections cover all three with environment-scoped configs.

### 4.2 Layered test suite

| Layer | Purpose | Substrate |
|---|---|---|
| **Unit** | Mapping layer transforms | Config-driven; test cases live alongside configs |
| **Contract** | Endpoint shape against athena APIs | Postman collections, CI against sandbox, scheduled against preview |
| **Integration** | Async patterns (Bulk FHIR three-step poll, subscriptions rest-hook if alpha lands) | Small test runner that drives polling loop and asserts terminal states |
| **Schema validation** | CCDA round-trip; FHIR shape validation | Every received CDA parses without lossy fields; mapping output validates against Brook FHIR shape |
| **Patient matching matrix** | Dedicated coverage for MRN + provider ID + Brook patient ID + DOB logic | Test cases: clean match, MRN-only, DOB mismatch with name match, cross-clinic transfer, missing fields |
| **Idempotency / replay** | Every push handler is replay-safe | Fire same event twice → assert one athena POST, one logged delivery |
| **Manual UI validation** | What IS consultant validates during Solution Validation | Eyeball confirmation per workflow in athena UI |

### 4.3 Regression

- Postman + harnesses in shared workspace.
- CI hook on integration layer repo.
- Nightly run against preview with results posting to Integration Health Dashboard channel.
- Schema drift alerts surface within 24 hours (before athena tells us).

---

## 5. Linear hygiene — action required

### 5.1 Project rename + new project

The existing "Partner Integration" project ([47695c97](https://linear.app/brook-health/project/partner-integration-94b66c687e71)) currently contains UMMH/Redox ORM, PAP CSV, and cross-clinic patient ingest bugs. None of it is athena marketplace work. Examples in this project today: AAR-238 (Redox order ingest demographics), AAR-247 (Redox lead provider), AAR-263 (name+DOB match logic), AAR-265 (cross-clinic duplicate monitoring), AAR-329 (Redox order consent), AAR-302 (program eligibility in POP).

**Rename:**
- Existing project → **"Patient Acquisition Integration — Operations"** (or shorter: **"PAP Integration — Ops"**)
- New project → **"athena Marketplace Integration"**

### 5.2 Tickets to create under the new project

| ID | Item | Type | Status today |
|---|---|---|---|
| 0a | Marketplace onboarding (case submission, preview env, IS consultant, ANC) | Admin tracker | No ticket |
| 0b | Tech spec revision (11 use cases, matches expanded spec in revision) | Tracker | No ticket |
| P0 | Foundation epic (the platform itself) | Epic | No ticket |
| P1a | CCDA inbound epic | Epic | No ticket |
| P1b | Clinical document upload epic | Epic | IDEA-21 + IDEA-25 exist as New Signal — promote and link |
| P2 | Orders epic | Epic | No ticket; blocked on Andrew + clinician |
| P3 | Bulk FHIR patient ingest epic | Epic | IDEA-20 exists as New Signal — promote |
| P4 | Notes / Escalations epic | Epic | No ticket |
| P5 | Billing real-time charge posting epic | Epic | No ticket (ENG-624 was narrow legacy) |

---

## 6. Open dependencies and blockers

| # | Item | Owner | Blocks |
|---|---|---|---|
| 1 | Andrew's review of expanded tech spec and orders dedup logic | Andrew Rosenthal | Most downstream external sharing; Phase 2 lock |
| 2 | Orders workflow assumption verified with Brook nurse clinician | Jason | Phase 2 scope lock |
| 3 | Contract resign with Rachel (resets 6-month clock) | Jason / Rachel | Onboarding restart |
| 4 | Spec re-sign with Joanna Bao (after 11-use-case spec finalizes) | Jason | Solution Validation |
| 5 | FHIR Subscriptions alpha access + pricing | Rachel / athena | Phase 2/3 real-time signals (have polling fallback) |
| 6 | athena Data View pricing + access | Rachel / athena | Analytics path (parallel, not critical) |
| 7 | Preview env case submission and provisioning (3-4 day SLA) | Jason | Phase 0 hello-world |

---

## 7. Out of scope (explicit, per vision brief)

- Device readings push to athena (no clear value path, no agreed standard).
- Discrete medication / order data push into athena (document-based for now, see Phase 1b).
- Single Sign-On into athenaNet from Brook applications (prohibited by athena API ToS).
- Bulk historical data conversion (prohibited by athena API ToS).
- Brook Health Companion patient-mediated FHIR access (strategic R&D, not v1).
- Re-platforming Redox onto the new foundation (future consideration once platform matures).

---

## 8. Reference — existing platform context the plan inherits

| Reference | Why it matters |
|---|---|
| [Services Interaction (Brook architecture)](https://app.notion.com/p/2f6df47a35be81728a1ff0b069d7ff8f) | Existing Integration Event Worker (Go), Integration Past Event Worker (Go), Dataplatform (Go) — the event substrate the integration layer fans into |
| [Event-Driven Architecture](https://app.notion.com/p/2f6df47a35be811db125d6dfb346b2ff) | Existing SQS / SNS / Lambda pattern; we extend, don't reinvent |
| [FHIR Datastore: Agentic Data Modeling](https://app.notion.com/p/2f6df47a35be810085c3cd8e3806ada9) | Brook → FHIR R4 canonical mapping; analytics path (HealthLake + Snowflake + dbt, currently blocked on SCP) |
| [Integration PX: Partner Integration Health Dashboard](https://linear.app/brook-health/project/integration-px-partner-integration-health-dashboard-01ede53f4eb3) | 9-category error taxonomy; logging destination for integration layer |
| [IDEA-40 PAP Column Mapper](https://linear.app/brook-health/issue/IDEA-40/pap-column-mapper-ops-tooling-for-onboarding-new-partner-csv-schemas) | Seed of mapping-as-UI for the long-term mapping layer story |
| [IDEA-29 Schema versioning and partner update framework](https://linear.app/brook-health/issue/IDEA-29/schema-versioning-and-partner-update-framework) | Committed — informs how mapping config schema versions over time |

---

## 9. What to do with this document

This plan is the eng-facing companion to the strategic Vision & Product Brief. Suggested next moves:

1. Walk the plan with eng leads (Tony as primary developer, plus the teams whose services it touches: Care Interface, Programs and Integrations, DNA for FHIR alignment).
2. Resolve the orders workflow assumption with a Brook nurse clinician before Phase 0 exit.
3. Get Andrew's review on the orders dedup logic.
4. Decide on the Linear project rename and create the new project.
5. Promote IDEA-20, IDEA-21, IDEA-25 from New Signal to active epics under the new project.
6. Submit the athena marketplace case to provision the preview environment (gates Phase 0 hello-world).
