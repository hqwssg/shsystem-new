package com.example.carbon.emission.model.dto;

import com.example.carbon.emission.model.entity.UncertaintyParamResult;
import com.example.carbon.emission.model.entity.UncertaintyRun;
import com.example.carbon.emission.model.entity.UncertaintyRunScope;
import lombok.Data;

import java.util.List;

/**
 * 不确定性模拟运行结果详情 DTO
 * <p>
 * 组装单次模拟运行的完整输出：O3/O4（运行记录的配置快照、统计量、
 * 置信区间与验证结论）+ O7（Scope 级完整性评估）+ O1（参数级归一化
 * 与 Beta 分布参数）。
 */
@Data
public class UncertaintyRunDetailDto {

    /**
     * 运行记录（O3/O4：配置快照 + 统计量 + 验证结论）
     */
    private UncertaintyRun run;

    /**
     * Scope 级完整性评估列表（O7）
     */
    private List<UncertaintyRunScope> scopes;

    /**
     * 参数级归一化与 Beta 分布参数列表（O1）
     */
    private List<UncertaintyParamResult> params;
}
