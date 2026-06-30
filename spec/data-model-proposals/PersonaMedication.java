// PROPOSAL — not a PR. For Brook Backend team review.
// FHIR R4 mapping: MedicationRequest (https://hl7.org/fhir/R4/medicationrequest.html)
//                  or MedicationStatement (https://hl7.org/fhir/R4/medicationstatement.html)
// Pattern source: PersonaDiagnosis.java (PAI-184) and CurrentMedications.java
//   (src/main/java/ai/brook/api/caremanagement/model/CurrentMedications.java)
// Mongo collection: persona_medications (NEW — does not exist in brook-backend as of 2026-06-30 scan)
//
// DESIGN NOTE: This is a NEW top-level collection, parallel to the care plan section
// PatientCarePlans.currentMedications[]. The care plan section remains the care team's
// editable medication list. This collection receives EHR-sourced discrete medications
// from CCDA/Bulk FHIR. The Backend team must decide whether to surface both in POCAR,
// and whether to merge/deduplicate across sources. See data-model-gaps.md decision #2.

package ai.brook.data.persona.medication;

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

/**
 * EHR-sourced discrete medication record for a patient.
 *
 * <p>FHIR R4 maps to: {@code MedicationRequest} (prescribed medications) or
 * {@code MedicationStatement} (patient-reported or EHR-sourced medication history).
 * In the CCDA context, medication section entries map to {@code MedicationStatement}
 * since CCDA does not always carry prescriber/intent metadata required for
 * {@code MedicationRequest}.</p>
 *
 * <p>Key FHIR fields covered: {@code medication[x]} (→ medicationName + rxNormCode),
 * {@code subject} (→ personaId), {@code status} (→ status), {@code dateAsserted}
 * (→ ingestedAt), {@code informationSource} (→ source), {@code dosage[].text}
 * (→ dosageText), {@code dosage[].route} (→ route), {@code dosage[].timing.code}
 * (→ frequencyText), {@code effectivePeriod.start} (→ effectiveStart),
 * {@code effectivePeriod.end} (→ effectiveEnd).</p>
 */
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@Document(collection = PersonaMedication.COLLECTION_NAME)
@CompoundIndexes({
        @CompoundIndex(
                name = "persona_status_effective",
                def = "{ 'persona_id': 1, 'status': 1, 'effective_start': -1 }"
        ),
        @CompoundIndex(
                name = "persona_source_ref",
                def = "{ 'persona_id': 1, 'source': 1, 'source_medication_id': 1 }",
                sparse = true,
                unique = true
        )
})
public class PersonaMedication {

    public static final String COLLECTION_NAME = "persona_medications";

    // ──────────────────────────────────────────────────────────────
    // Identity
    // ──────────────────────────────────────────────────────────────

    @Id
    @Field("_id")
    private String id; // Brook-generated UUID

    @Field("persona_id")
    private String personaId; // FK → persona._id

    @Nullable
    @Field("provider_office_id")
    private String providerOfficeId; // FK → provider_office._id

    // ──────────────────────────────────────────────────────────────
    // Source tracking
    // ──────────────────────────────────────────────────────────────

    @Field("source")
    private MedicationSource source;

    @Nullable
    @Field("source_medication_id")
    private String sourceMedicationId;
    // EHR-assigned medication/prescription identifier.
    // Compound unique index with persona_id + source prevents duplicate ingest.

    // ──────────────────────────────────────────────────────────────
    // Medication identity
    // ──────────────────────────────────────────────────────────────

    @Field("medication_name")
    private String medicationName;
    // Display name (e.g., "Metformin 500mg"). Required. Snapshotted from EHR at ingest.

    @Nullable
    @Field("rx_norm_code")
    private String rxNormCode;
    // RxNorm concept unique identifier (e.g., "860975").
    // FHIR MedicationStatement.medication[x]: medicationCodeableConcept.coding[system=rxnorm].code
    // Nullable: CCDA provides RxNorm when available; older entries may be name-only.

    @Nullable
    @Field("ndc_code")
    private String ndcCode;
    // National Drug Code. May be present in CCDA medication section.

    // ──────────────────────────────────────────────────────────────
    // Status and timing
    // ──────────────────────────────────────────────────────────────

    @Field("status")
    private MedicationStatus status;
    // FHIR MedicationStatement.status: active | inactive | intended | stopped | on-hold | unknown

    @Nullable
    @Field("effective_start")
    private Instant effectiveStart;
    // When the medication was started (FHIR MedicationStatement.effectivePeriod.start)

    @Nullable
    @Field("effective_end")
    private Instant effectiveEnd;
    // When the medication was stopped (FHIR MedicationStatement.effectivePeriod.end)
    // Null = currently active

    // ──────────────────────────────────────────────────────────────
    // Dosage — structured where possible, freetext fallback
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("dosage_text")
    private String dosageText;
    // Full SIG text from CCDA (e.g., "Take 1 tablet by mouth twice daily with food").
    // FHIR MedicationStatement.dosage[0].text

    @Nullable
    @Field("dose_value")
    private Double doseValue;
    // Numeric dose quantity (e.g., 500.0). FHIR dosage[].doseAndRate[].doseQuantity.value

    @Nullable
    @Field("dose_unit")
    private String doseUnit;
    // Unit of dose (e.g., "mg", "mL"). FHIR dosage[].doseAndRate[].doseQuantity.unit

    @Nullable
    @Field("route")
    private String route;
    // Route of administration (e.g., "oral", "subcutaneous"). FHIR dosage[].route.text

    @Nullable
    @Field("frequency_text")
    private String frequencyText;
    // Human-readable frequency (e.g., "twice daily", "every 8 hours"). FHIR dosage[].timing.code.text

    // ──────────────────────────────────────────────────────────────
    // Prescriber (optional — present in MedicationRequest, less common in MedicationStatement)
    // ──────────────────────────────────────────────────────────────

    @Nullable
    @Field("prescriber_name")
    private String prescriberName;
    // Display name of ordering/prescribing provider (snapshotted from EHR)

    @Nullable
    @Field("prescriber_npi")
    private String prescriberNpi;

    // ──────────────────────────────────────────────────────────────
    // Audit
    // ──────────────────────────────────────────────────────────────

    @Field("ingested_at")
    @CreatedDate
    private Instant ingestedAt;

    @Nullable
    @Field("updated_at")
    @LastModifiedDate
    private Instant updatedAt;

    // ──────────────────────────────────────────────────────────────
    // Enums
    // ──────────────────────────────────────────────────────────────

    /**
     * Origin of this medication record. Pattern matches DiagnosisSource (PAI-184).
     */
    public enum MedicationSource {
        ATHENA_CCDA,       // From athena CCDA medication section (Phase 1a)
        ATHENA_BULK_FHIR,  // From athena Bulk FHIR MedicationRequest/Statement (Phase 3)
        REDOX,             // Received via Redox
        MANUAL,            // Entered manually by care team
        OTHER
    }

    /**
     * FHIR MedicationStatement.status value set (R4).
     * See: https://hl7.org/fhir/R4/valueset-medication-statement-status.html
     */
    public enum MedicationStatus {
        ACTIVE,
        INACTIVE,
        INTENDED,
        STOPPED,
        ON_HOLD,
        UNKNOWN,
        ENTERED_IN_ERROR
    }
}
