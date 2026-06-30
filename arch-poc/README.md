# Brook Integration Layer — Architectural POC

**CCDA Inbound Vertical Slice**

> Status: POC skeleton — all three layers wired, fully mocked (no live credentials required).
> Generated: 2026-06-30

---

## What this is

A standalone Python skeleton demonstrating the three-layer integration architecture
proposed in `reference/brook-integration-platform-athena-griffin-v1.md`. It implements
one complete end-to-end vertical slice: CCDA inbound from athena.

No Brook internal imports. No live API calls. All layers are mocked but structurally
correct. Tests run with `pytest` and pass without external credentials.

---

## How to run

```bash
pip install -r requirements.txt

# Run the full vertical slice (shows both runs: initial ingest and idempotent replay)
python main.py

# Run the test suite
pytest tests/ -v
```

---

## Three-layer architecture

### Layer 1 — Integration layer (`integration_layer/`)

**What it owns:** athena wire-protocol concerns. This layer knows athena — nothing else does.

| Component | Purpose |
|-----------|---------|
| `auth.py` | OAuth2 client credentials token management. Mocks the token endpoint call; in production hits `https://api.platform.athenahealth.com/oauth2/v1/token` with Basic auth. Mirrors `AthenaApiService.java` auth flow (brook-backend). |
| `athena_adapter.py` | Retrieves CCDA XML from athena. Implements exponential backoff with `Retry-After` header parsing. Generates idempotency keys (patient\_id + document\_type + daily date bucket). Returns raw XML — does not parse it. |

**Layer 1 does not know about Brook entities.** It returns a raw CCDA XML string.
That is the seam — nothing from athena's protocol bleeds past this boundary.

**Idempotency key design:** `SHA-256(patient_id:CCDA:YYYY-MM-DD)[:32]`

The daily bucket is the adapter-level dedup window — the same patient's CCDA
pulled twice in one day uses the same key, preventing redundant HTTP calls.
Store-level dedup (Layer 3) uses a finer key derived from EHR source IDs.

**Retry/backoff source:** The Java precedent is `ExponentialBackoffInterceptor.java`
in brook-backend. That class exists but is NOT wired into the production
`AthenaApiService` or `RedoxApiService` OkHttp client builders — a gap identified
by the recon scan. This Python layer wires it correctly: `Retry-After` header
honored first, exponential backoff fallback.

### Layer 2 — Mapping layer (`mapping_layer/`)

**What it owns:** CCDA XML in, Brook-shaped entity dicts out. Config-driven.

| Component | Purpose |
|-----------|---------|
| `ccda_mapper.py` | Parses C-CDA XML using Python's standard `xml.etree.ElementTree`. Extracts four CCDA sections. Produces Brook entity dicts that mirror the field names (snake\_case) from `spec/data-model-proposals/*.java`. Sets `source = ATHENA_CCDA` on every entity. |
| `mapping_config/athena.yaml` | Partner-keyed mapping config. Defines which CCDA sections to extract, what LOINC codes identify them, what Brook entity type they produce, and how status codes normalize. |

**Config-over-code:** A future `griffin.yaml` or `epic.yaml` in `mapping_config/`
is a new config file, not new mapper code. This is the anti-pattern the integration
platform is designed to replace: `RedoxService.java` (82.7KB) has all Redox
transform logic hardcoded inline — a single brittle class that owns too much.

**CCDA sections mapped:**

| LOINC | Section | Brook entity |
|-------|---------|-------------|
| 11450-4 | Problem List | `PersonaProblem` |
| 10160-0 | History of Medication Use | `PersonaMedication` |
| 46240-8 | Encounter History | `PersonaEncounter` |
| 48765-2 | Allergies, Adverse Reactions, Alerts | `PersonaAllergy` |

**Field names** mirror the Java proposals in `spec/data-model-proposals/*.java`
(snake\_case, matching `@Field` annotations and `@JsonNaming(SnakeCaseStrategy.class)`).

### Layer 3 — Platform layer (`platform_layer/`)

**What it owns:** Brook persistence and event emission. It knows Brook's canonical model,
not athena's.

| Component | Purpose |
|-----------|---------|
| `clinical_store.py` | Writes entities to in-memory collections that mirror the proposed MongoDB collection shapes. Enforces upsert-by-source-key idempotency: if `(persona_id, source, source_entity_id)` already exists, the write is skipped and `is_duplicate=True` is returned. |
| `event_publisher.py` | Emits a Brook integration event (`CCDA_{EntityType}_INGESTED`) for each new entity. Suppresses events for duplicate entities — replay-safe by design. |

**Platform layer does not know about CCDA.** It receives Brook-shaped entity dicts
from the mapping layer. Source format is irrelevant here.

---

## How this prevents the Redox seam-bug class

The recon identified two classes of active seam bugs in the Redox integration:

**AAR-247** (lead provider not written for existing patients): The Redox ingest
path processes patient matching and field updates in the same code path as the
initial write. When a patient already exists, the code flow skips writes it should
not skip. This is a consequence of mapping logic (which fields to write) being
entangled with ingest logic (is this patient new or existing).

**AAR-329** (consent not honored on rematch): The Redox order flow re-stamps RPM
consent even for CCM-only clinics when a patient rematches across clinics. This
happens because the consent logic lives inside the same 82.7KB class that owns
matching, field mapping, and order processing — no defined layer owns consent
semantics.

Both bugs are in `RedoxService.java` — a single class owning too many concerns
without layer boundaries.

**The three-layer pattern prevents this by owning responsibilities explicitly:**

- Layer 1 owns wire-protocol concerns (auth, retry, rate limits). It cannot accidentally
  apply consent logic or decide which fields to update.
- Layer 2 owns field mapping. It produces entity dicts from raw EHR data and nothing
  else. It cannot accidentally write to a store or update a patient record.
- Layer 3 owns upsert semantics and event emission. The `is_duplicate` flag from
  `ClinicalStore.write()` drives `EventPublisher.emit()` suppression. Replay safety
  is enforced at the store boundary, not scattered across application code.

When an entity arrives that already exists, the store detects it at the compound
key `(persona_id, source, source_entity_id)` — the same compound-unique-index
pattern used by `EmrLog` for outbound idempotency in brook-backend — and the
event publisher suppresses the downstream event. No application code outside
Layer 3 needs to reason about replay.

---

## CCDA clinical data flow into proposed entity models

```
athena CCDA XML
    │
    ▼  Layer 1 (AthenaAdapter)
Raw CCDA XML + idempotency_key
    │
    ▼  Layer 2 (CCDAMapper + athena.yaml)
    ├── LOINC 11450-4 (Problem List)
    │       └── PersonaProblem dicts
    │             { persona_id, source: ATHENA_CCDA, source_problem_id,
    │               icd10_code, display_name, clinical_status,
    │               verification_status, onset_date, ... }
    │
    ├── LOINC 10160-0 (Medications)
    │       └── PersonaMedication dicts
    │             { persona_id, source: ATHENA_CCDA, source_medication_id,
    │               medication_name, rx_norm_code, status, dosage_text,
    │               dose_value, dose_unit, route, effective_start, ... }
    │
    ├── LOINC 46240-8 (Encounters)
    │       └── PersonaEncounter dicts
    │             { persona_id, source: ATHENA_CCDA, source_encounter_id,
    │               status, encounter_type, period_start, period_end,
    │               providers[], reason_codes[], location_name, ... }
    │
    └── LOINC 48765-2 (Allergies)
            └── PersonaAllergy dicts
                  { persona_id, source: ATHENA_CCDA, source_allergy_id,
                    clinical_status, verification_status, allergy_type,
                    criticality, allergen_name, rx_norm_code,
                    onset_date, reactions[], ... }
    │
    ▼  Layer 3 (ClinicalStore)
    ├── persona_problems     ← PersonaProblem (new collection)
    ├── persona_medications  ← PersonaMedication (new collection)
    ├── persona_encounters   ← PersonaEncounter (new collection, MISSING from brook-backend)
    └── persona_allergies    ← PersonaAllergy (new collection)
    │
    ▼  Layer 3 (EventPublisher)
    └── CCDA_PersonaProblem_INGESTED
        CCDA_PersonaMedication_INGESTED
        CCDA_PersonaEncounter_INGESTED
        CCDA_PersonaAllergy_INGESTED
        (suppressed on replay — is_duplicate=True)
```

**PersonaDiagnosis note:** The `PersonaDiagnosis` model (PAI-184, confirmed merged
in brook-backend HEAD) embeds in `persona.diagnoses[]`. The Backend team must decide
whether CCDA problem list entries route to `PersonaDiagnosis` (source=ATHENA\_CCDA,
using the existing `persona.diagnoses[]` canonical store) or to a separate
`PersonaProblem` collection. This POC uses `PersonaProblem` as a placeholder.
When the decision is made, update `brook_entity` in `mapping_config/athena.yaml`
— no mapper code changes required.

---

## Event substrate decision needed before production wiring

The recon identified THREE event substrates in production (findings.md):

1. **AWS SQS** — device data path. `services-data` sends device readings via
   `SQSSender.java`. `brook-backend` `GenericQueueProcessor` consumes via
   `QueueAlias.BROOK/BROOK_PLUS/NOTIFICATIONS`.

2. **MongoDB CDC** — care-nexus path. A Go service watches MongoDB change streams
   and writes derived `patient_features` to PostgreSQL.

3. **Redis Streams (Valkey)** — data-platform CIO service path for webhook-to-processing
   queuing.

The build plan states "the existing SQS-backed worker pattern is the substrate" — this
applies only to device data. The athena integration layer must make an explicit choice:

- **SQS**: matches device data pattern; familiar infra; requires the integration events
  to fan into the `GenericQueueProcessor` action model or a new queue alias.
- **MongoDB CDC**: if clinical entities land in MongoDB, care-nexus CDC picks them up
  automatically for `patient_features` updates. Low additional infra cost if MongoDB
  is already the target persistence.
- **Redis Streams**: matches the data-platform CIO pattern; appropriate if the consumer
  is data-platform (analytics / Snowflake sync) rather than brook-backend.

The "Integration Event Worker (Go)" and "Integration Past Event Worker (Go)"
referenced in the build plan are NOT found as source-level repos in the Brookai org.
This decision cannot be deferred past the Phase 0 exit criteria.

This POC uses an `InMemoryEventBus` with a `TODO: wire to real Brook event substrate`
comment in `event_publisher.py`.

---

## What is mocked vs. what would be real in production

| Component | POC (mocked) | Production |
|-----------|-------------|------------|
| `AthenaOAuth2Client.get_bearer_token()` | Returns a fake token string | POST to `https://api.platform.athenahealth.com/oauth2/v1/token` with Basic auth |
| `AthenaAdapter.get_ccda()` | Returns embedded CCDA XML fixture | GET `/v1/{practice_id}/ccda/{patient_id}/ccda` with Bearer token |
| `time.sleep()` in retry loop | `sleep(0)` (no delay) | `sleep(delay)` with computed backoff |
| `ClinicalStore` | In-memory dict | MongoDB collections: `persona_problems`, `persona_medications`, `persona_encounters`, `persona_allergies` |
| `InMemoryEventBus` | Thread-safe dict | AWS SQS, MongoDB CDC, or Redis Streams (see Event Substrate section above) |
| CCDA XML parser | Python `xml.etree.ElementTree` | Same in production; a full CDA library (e.g., `cda-python` or a Java library in brook-backend) would be safer for production C-CDA compliance |
| Secrets | Environment variables / hardcoded defaults | Kubernetes Secret → `ATHENA_CLIENT_ID` / `ATHENA_CLIENT_SECRET` env injection |

---

## Directory structure

```
arch-poc/
  integration_layer/
    __init__.py
    auth.py             # OAuth2 token management stub
    athena_adapter.py   # Mocked athena client + CCDA fixture + retry/backoff
  mapping_layer/
    __init__.py
    ccda_mapper.py      # CCDA XML → Brook entity dicts
    mapping_config/
      athena.yaml       # Partner-keyed mapping config
  platform_layer/
    __init__.py
    event_publisher.py  # In-memory event bus + suppression logic
    clinical_store.py   # In-memory MongoDB-mirrored store + upsert idempotency
  tests/
    __init__.py
    test_ccda_flow.py   # End-to-end vertical slice test
    test_idempotency.py # Replay-safety and duplicate suppression tests
  main.py               # Entry point: runs both runs (initial + replay)
  requirements.txt
  README.md
```
