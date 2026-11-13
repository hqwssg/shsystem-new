package com.ruoyi.carbon.report.source;

import java.util.Arrays;
import java.util.List;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

public enum ReportExcelType
{
    equipment("设备", List.of("名称", "类别", "数量", "单位", "型号", "能源种类", "备注"), "name"),
    monitoring("监测设备", List.of("名称", "型号", "精度", "量程", "安装位置", "检定周期"), "name"),
    workload("工作量", List.of("名称", "数量", "单位"), "name"),
    heat("热力", List.of("站点", "供暖面积", "耗热量系数"), "site");

    public final String label;
    public final List<String> headers;
    public final String keyField;

    ReportExcelType(String label, List<String> headers, String keyField)
    {
        this.label = label;
        this.headers = headers;
        this.keyField = keyField;
    }

    public static ReportExcelType from(String raw)
    {
        if (raw == null || raw.isBlank())
        {
            throw new ServiceException("未知导入类型", HttpStatus.BAD_REQUEST);
        }
        try
        {
            return ReportExcelType.valueOf(raw.trim().toLowerCase());
        }
        catch (IllegalArgumentException ex)
        {
            throw new ServiceException("未知导入类型", HttpStatus.BAD_REQUEST);
        }
    }

    public static boolean isKnown(String raw)
    {
        return Arrays.stream(values()).anyMatch(item -> item.name().equalsIgnoreCase(raw));
    }
}
