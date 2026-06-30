# Integration-POCs

Multi-agent reconnaissance, gap analysis, architectural POCs, and Linear project spec for the Brook integration platform (athena + Griffin v1).

This repo is read-only relative to all Brook source repos. It contains proposals, findings, and proof-of-concept code only. No PRs to Brook repos originate here.

---

## Repo Structure

```
reference/                        # Input documents (read-only)
  brook-integration-platform-athena-griffin-v1.md   # Build plan (hypothesis, not ground truth)
  brook_data_model_gaps.md        # Jason's seed gap doc (Persona registration model)

findings.md                       # Recon agent output — plan vs. code, per pillar
recon-summary.md                  # Top 5 contradictions between plan and real code

spec/
  data-model-gaps.md              # Clinical entity gap analysis (extends seed doc)
  data-model-proposals/           # Java class drafts for missing/partial entities
    PersonaEncounter.java
    PersonaMedication.java
    PersonaProblem.java
    PersonaAllergy.java
    PersonaLab.java
    PersonaVital.java
  linear-project.md               # Linear-ready project spec
  dev-ready-report.md             # Dev-readiness review: verdict + blockers

wire-pocs/                        # Standalone athena API contract proofs (Brook-independent)
  foundation/                     # OAuth2, retry/backoff, idempotency keys
  ccda-inbound/                   # GET CCDA document from athena
  clinical-doc-upload/            # POST clinical document to athena (live endpoint)
  orders/                         # Lab order creation + status polling
  bulk-fhir/                      # Async FHIR $export + NDJSON download
  notes-escalations/              # Patient notes POST/GET
  billing/                        # Eligibility check + CPT charge posting

arch-poc/                         # Three-layer architectural POC (Python, 40 tests)
  integration_layer/              # Layer 1: mocked athena adapter + auth stub
  mapping_layer/                  # Layer 2: CCDA parser + partner-keyed YAML config
  platform_layer/                 # Layer 3: event publisher + clinical entity store
  tests/                          # pytest suite: full flow + idempotency
  main.py                         # Entry point: runs two passes, prints idempotency proof
```

---

## How to Use This

### For Jason (product review)

Start here, in order:

1. **`recon-summary.md`** — 5 paragraphs. What the code contradicts in the plan. Read before anything else.
2. **`spec/data-model-gaps.md`** — Entity status table. Confirms PAI-184 merged. Surfaces the PersonaDiagnosis/PersonaProblem duality as the #1 blocking question.
3. **`spec/linear-project.md`** — The Linear spec. Key Decisions section is the primary artifact for your review. 10 decisions, each with owner, blocker, and impact-if-deferred.
4. **`spec/dev-ready-report.md`** — Verdict: READY WITH CONDITIONS. 3 blockers listed. What engineering can start on immediately.

### For an engineer onboarding

1. Read `findings.md` for the full recon (plan vs. code, per pillar, with file citations).
2. Read `spec/data-model-gaps.md` for clinical entity status.
3. Review the Java proposals in `spec/data-model-proposals/` — these are PROPOSALS for Backend team reaction, not PRs.
4. Run the arch POC locally to see the three-layer pattern end-to-end:
   ```bash
   cd arch-poc
   pip install -r requirements.txt
   python main.py
   pytest tests/
   ```
5. For a specific pillar, open `wire-pocs/<pillar>/README.md` first, then `poc.py`. Run with `--dry-run` to see the request shape without needing athena credentials.

### For athena sandbox testing

Each wire POC requires three env vars:
```bash
export ATHENA_CLIENT_ID=...
export ATHENA_CLIENT_SECRET=...
export ATHENA_PRACTICE_ID=...
```

Run any pillar POC:
```bash
cd wire-pocs/ccda-inbound
pip install requests
python poc.py --patient-id 12345
# or dry-run (no credentials needed):
python poc.py --patient-id 12345 --dry-run
```

Import the Postman collection (`postman-collection.json` in each pillar dir) for manual testing. Set `athena_client_id`, `athena_client_secret`, `athena_practice_id` in your Postman environment.

---

## What This Is Not

- Not a PR to any Brook repo
- Not a production-ready integration layer
- Not a claims about what Brook's architecture is — every finding cites real file paths or is flagged as "assumption, needs verification"

---

## Commit History

| Commit | Agent | Contents |
|--------|-------|----------|
| `7afc2e9` | orchestrator | Reference docs |
| `7352170` | recon-agent | findings.md, recon-summary.md |
| `e48bfd6` | gap-agent | spec/data-model-gaps.md, spec/data-model-proposals/ |
| `68bde39` | build-agent-spec | spec/linear-project.md |
| `7297bf2` | build-agent-arch | arch-poc/ |
| `ca4d72f` | build-agent-wire | wire-pocs/ |
| `ea766ee` | dev-ready-agent | spec/dev-ready-report.md |
