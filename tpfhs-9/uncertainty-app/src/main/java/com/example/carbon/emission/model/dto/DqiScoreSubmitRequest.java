package com.example.carbon.emission.model.dto;

import lombok.Data;

import java.util.List;

/**
 * I2 人工复核提交请求 DTO（单排放源单参数类型一批维度评分）
 */
@Data
public class DqiScoreSubmitRequest {

    /**
     * 提交项列表
     */
    private List<DqiScoreSubmitItem> items;
}
