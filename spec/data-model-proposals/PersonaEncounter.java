// PROPOSAL — not a PR. For Brook Backend team review.
// FHIR R4 mapping: Encounter (https://hl7.org/fhir/R4/encounter.html)
// Pattern source: PersonaDiagnosis.java (PAI-184 merged, src/main/java/ai/brook/data/persona/diagnosis/PersonaDiagnosis.java)
// Mongo collection: persona_encounters (NEW — does not exist in brook-backend as of 2026-06-30 scan)

package ai.brook.data.persona.encounter;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.Id;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.mongodb.core.index.CompoundIndex;
import org.springframework.data.mongodb.core.index.CompoundIndexes;
import org.springframework.data.mongodb.core.mapping.Document;
import org.springframework.data.mongodb.core.mapping.Field;

import javax.annotation.Nullable;
import java.time.Instant;
import java.util.List;

/**
 * EHR-sourced clinical encounter record for a patient.
 *
 * <p>FHIR R4 maps to: {@code Encounter} resource. Key required/important
 * FHIR fields covered: {@code status}, {@code class} (→ encounterClass),
 * {@code type} (→ encounterType), {@code period.start} / {@code period.end},
 * {@code participant} (→ providers[]), {@code reasonCode} (→ reasonCodes[]),
 * {@code serviceProvider} (→ providerOfficeId), {@code subject} (→ personaId).</p>
 *
 * <p>This model is a discrete top-level collection — NOT embedded in Persona —
 * to allow querying by encounter date, type, and provider without loading the
 * full Persona document. A patient may have many encounters over their care history.</p>
 *
 * <p>Source enum values {@code ATHENA_CCDA} and {@code ATHENA_BULK_FHIR} are proposed;
 * they must be added to a Brook-wide {@code EncounterSource} or a parallel update to
 * {@code DiagnosisSource} — TBD by Backend team. See data-model-gaps.md.</p>
 */
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@Document(collection = PersonaEncounter.COLLECTION_NAME)
@CompoundIndexes({
        @CompoundIndex(
                name = "persona_encounter_period",
                def = "{ 'persona_id': 1, 'period_start': -1 }"
        ),
        @CompoundIndex(
                name = "persona_source_ref",
                def = "{ 'persona_id': 1, 'source': 1, 'source_encounter_id': 1 }",
                sparse = true,
                unique = true
        )
})
public class PersonaEncounter {

    public static final String COLLECTION_NAME = "persona_encounters";

    // ──────────────────────────────────────────────────────────────
    // Identity
    // ──────────────────────────────────────────────────────────────

    @Id
    @Field("_id")
    private String id; // Brook-generated UUID on ingest

    @Field("persona_id")
    private String personaId; // FK → persona._id (Brook MongoDB)

    @Nullable
    @Field("provider_office_id")
    private String providerOfficeId; // FK → provider_office._id (Brook MongoDB); FHIR serviceProvider

    // ──────────────────────────────────────────────────────────────
    // Source tracking
    // ──────────────────────────────────────────────────────────────

    @Field("source")
    private EncounterSource source; // Origin system

    @Nullable
    @Field("source_encounter_id")
    private String sourceEncounterId;
    // EHR-assigned encounter identifier (e.g., athena encounter ID from CCDA).
    // Compound unique index with persona_id + source prevents duplicate ingest.

    // ──────────────────────────────────────────────────────────────
    // FHIR Encounter core fields
    // ──────────────────────────────────────────────────────────────

    @Field("status")
    private EncounterStatus status;
    // FHIR Encounter.status: planned | arrived | triaged | in-progress | onleave | finished | cancelled

    @Nullable
    @Field("encounter_class")
    private String encounterClass;
    // FHIR Encounter.class (ActEncounterCode): AMB=ambulatory, IMP=inpatient, EMER=emergency, HH=home health
    // Free text in v1; future: HL7 v3 ActEncounterCode coded value

    @Nullable
    @Field("encounter_type")
    private String encounterType;
    // FHIR Encounter.type: e.g., "Office Visit", "Annual Wellness Visit", "Follow-up"
    // Free text in v1; future: SNOMED CT or CPT coded type

    @Nullable
    @Field("period_start")
    private Instant periodStart; // FHIR Encounter.period.start

    @Nullable
    @Field("period_end")
    private Instant periodEnd; // FHIR Encounter.period.end

    @Nullable
    @Field("providers")
    private List<EncounterProvider> providers;
    // FHIR Encounter.participant[]: attending, referring, consulting providers

    @Nullable
    @Field("reason_codes")
    private List<ReasonCode> reasonCodes;
    // FHIR Encounter.reasonCode: ICD-10 codes that motivated this encounter

    @Nullable
    @Field("location_name")
    private String locationName;
    // FHIR Encounter.location[].location display name (e.g., "Griffin Faculty Practice")

    @Nullable
    @Field("discharge_disposition")
    private String dischargeDisposition;
    // FHIR Encounter.hospitalization.dischargeDisposition (for inpatient only)

    // ──────────────────────────────────────────────────────────────
    // Audit
    // ──────────────────────────────────────────────────────────────

    @Field("ingested_at")
    @CreatedDate
    private Instant ingestedAt; // When Brook received and stored this record

    @Nullable
    @Field("updated_at")
    @LastModifiedDate
    private Instant updatedAt; // Last Brook-side update (e.g., re-ingest from new CCDA)

    // ──────────────────────────────────────────────────────────────
    // Nested types
    // ──────────────────────────────────────────────────────────────

    /**
     * Participating provider in an encounter.
     * FHIR: Encounter.participant
     */
    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public static class EncounterProvider {
        @Field("role")
        private String role; // "attending" | "referring" | "consulting" | "admitting"

        @Nullable
        @Field("provider_name")
        private String providerName; // Display name snapshot (not a FK)

        @Nullable
        @Field("npi")
        private String npi; // Provider NPI if available from EHR

        @Nullable
        @Field("provider_id")
        private String providerId; // EHR-assigned provider ID (athena providerid)
    }

    /**
     * Coded reason for the encounter.
     * FHIR: Encounter.reasonCode (CodeableConcept)
     */
    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public static class ReasonCode {
        @Field("system")
        private String system; // "ICD-10-CM" | "SNOMED-CT" | "CPT"

        @Field("code")
        private String code; // e.g., "E11.9"

        @Nullable
        @Field("display")
        private String display; // Human-readable name (snapshot from EHR)
    }

    // ──────────────────────────────────────────────────────────────
    // Enums
    // ──────────────────────────────────────────────────────────────

    /**
     * Origin of this encounter record.
     *
     * <p>Pattern matches {@code DiagnosisSource} in PAI-184. Must be kept in sync
     * if a unified source enum is introduced. ATHENA_CCDA and ATHENA_BULK_FHIR are
     * the integration-layer sources; MANUAL allows care team entry.</p>
     */
    public enum EncounterSource {
        ATHENA_CCDA,       // Pulled from athena CCDA document (Phase 1a)
        ATHENA_BULK_FHIR,  // Pulled from athena Bulk FHIR export (Phase 3)
        REDOX,             // Received via Redox (future: if Redox delivers encounter data)
        MANUAL,            // Entered manually by care team
        OTHER
    }

    /**
     * FHIR Encounter.status value set (R4).
     * See: https://hl7.org/fhir/R4/valueset-encounter-status.html
     */
    public enum EncounterStatus {
        PLANNED,
        ARRIVED,
        TRIAGED,
        IN_PROGRESS,
        ON_LEAVE,
        FINISHED,
        CANCELLED,
        ENTERED_IN_ERROR,
        UNKNOWN
    }
}
