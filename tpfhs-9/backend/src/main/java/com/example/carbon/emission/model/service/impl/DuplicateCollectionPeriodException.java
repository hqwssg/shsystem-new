package com.example.carbon.emission.model.service.impl;

import java.time.LocalDate;

/** 非累计采集点同一计费周期存在重复有效记录时抛出。 */
public class DuplicateCollectionPeriodException extends RuntimeException {
    private final Integer collectionPointType;
    private final Long collectionPointId;
    private final LocalDate billingCycleStartDate;
    private final LocalDate billingCycleEndDate;

    public DuplicateCollectionPeriodException(Integer collectionPointType, Long collectionPointId,
                                              LocalDate billingCycleStartDate, LocalDate billingCycleEndDate) {
        super("非累计采集点存在重复有效计费周期：采集点=" + collectionPointId
                + "，周期=" + billingCycleStartDate + "至" + billingCycleEndDate);
        this.collectionPointType = collectionPointType;
        this.collectionPointId = collectionPointId;
        this.billingCycleStartDate = billingCycleStartDate;
        this.billingCycleEndDate = billingCycleEndDate;
    }

    public Integer getCollectionPointType() { return collectionPointType; }
    public Long getCollectionPointId() { return collectionPointId; }
    public LocalDate getBillingCycleStartDate() { return billingCycleStartDate; }
    public LocalDate getBillingCycleEndDate() { return billingCycleEndDate; }
}
