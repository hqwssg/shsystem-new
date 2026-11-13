package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CalculationNode;
import com.example.carbon.emission.model.entity.CalculationNodeData;
import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.repository.CalculationNodeDataRepository;
import com.example.carbon.emission.model.repository.CalculationNodeRepository;
import org.springframework.stereotype.Component;

import java.util.List;

/** 核算任务空数据门禁，避免没有任何有效采集结果时生成“成功但全为 0”的汇总。 */
@Component
public class ManualCalculationDataGuard {
    private static final int COLLECTION_NODE_TYPE = 3;
    private static final int NO_DATA_STATUS = 2;

    private final CalculationNodeRepository nodeRepository;
    private final CalculationNodeDataRepository dataRepository;

    public ManualCalculationDataGuard(CalculationNodeRepository nodeRepository,
                                      CalculationNodeDataRepository dataRepository) {
        this.nodeRepository = nodeRepository;
        this.dataRepository = dataRepository;
    }

    public boolean hasNoValidIncludedData(CalculationTemplate task) {
        if (task == null) {
            return false;
        }
        List<Long> includedCollectionNodeIds = nodeRepository
                .findByCalculationTemplateId(task.getId()).stream()
                .filter(node -> Integer.valueOf(COLLECTION_NODE_TYPE).equals(node.getTypeId()))
                .filter(node -> !Boolean.FALSE.equals(node.getIncludeInCalculation()))
                .map(CalculationNode::getId)
                .toList();
        if (includedCollectionNodeIds.isEmpty()) {
            return true;
        }
        List<CalculationNodeData> rows = dataRepository.findByCalculationNodeIdIn(includedCollectionNodeIds);
        if (rows.isEmpty()) {
            return true;
        }

        // 状态 3/4/5 只表示存在缺口或超范围，不能作为“有有效数据”的依据。
        // 只有完整数据，或不完整但确实产生了非零读数，才允许继续汇总。
        return rows.stream().noneMatch(data -> {
            if (data == null || Integer.valueOf(NO_DATA_STATUS).equals(data.getDataStatus())) {
                return false;
            }
            if (Integer.valueOf(1).equals(data.getDataStatus())) {
                return true;
            }
            return nonZero(data.getEnergyMeasurementValue())
                    || nonZero(data.getCarbonEmission());
        });
    }

    private boolean nonZero(java.math.BigDecimal value) {
        return value != null && value.signum() != 0;
    }
}
