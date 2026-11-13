package com.example.carbon.emission.model.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class CreateTemplateRequest {
    @NotBlank(message = "模版名称不能为空")
    @Size(max = 200, message = "模版名称不能超过200个字符")
    private String name;
    @Size(max = 500, message = "模版描述不能超过500个字符")
    private String description;
    @NotNull(message = "创建人不能为空")
    private Long createdBy;
    /**
     * 模版类型：1-节点模版（默认）；2-核算模版
     */
    @Min(value = 1, message = "模版类型只能为1或2")
    @Max(value = 2, message = "模版类型只能为1或2")
    private Integer templateType;
    private Long companyDeptId;
}
