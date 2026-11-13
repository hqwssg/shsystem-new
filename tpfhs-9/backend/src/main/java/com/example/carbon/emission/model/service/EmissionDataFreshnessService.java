package com.example.carbon.emission.model.service;

/**
 * Tracks the data revision consumed by each calculation task.
 * The revision is deliberately stored in small compatibility tables so an
 * existing installation can be upgraded without changing business tables.
 */
public interface EmissionDataFreshnessService {
    long currentRevision(Long templateId);

    boolean needsRecalculation(Long templateId);

    /** Marks templates containing the collection point as changed. */
    int markCollectionPointChanged(Integer collectionPointType, Long collectionPointId, String reason);

    /** Captures the current revision for a newly created calculation task. */
    long captureCalculation(Long calculationTemplateId, Long templateId);

    /** Clears the pending flag only after the calculation completed successfully. */
    void completeCalculation(Long calculationTemplateId, Long templateId, long revision);
}
