package com.example.carbon.emission.model.service.impl;

/** 月度发布协调器的结构化结果，供调度、日志和后续后台任务复用。 */
public record MonthlyPublicationResult(String status,
                                       int collectionRows,
                                       int nodeRows,
                                       int companyRows,
                                       String failureReason) {
}
