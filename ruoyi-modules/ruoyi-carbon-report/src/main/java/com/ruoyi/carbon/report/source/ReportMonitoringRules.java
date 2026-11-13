package com.ruoyi.carbon.report.source;

import java.util.List;
import java.util.stream.Stream;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

/** Names are descriptions, not unique device identifiers. Only storage limits constrain saving. */
public final class ReportMonitoringRules {
    private ReportMonitoringRules() { }

    public static boolean isBlank(ReportMonitoringDevice row) {
        return Stream.of(row.getName(), row.getModel(), row.getAccuracy(), row.getMeasurementRange(),
                row.getLocation(), row.getCalibrationFrequency(), row.getSourceTable(), row.getSourceId())
                .allMatch(value -> value == null || value.isBlank());
    }

    public static void validateLengths(List<ReportMonitoringDevice> rows) {
        for (int i = 0; i < rows.size(); i++) {
            ReportMonitoringDevice row = rows.get(i);
            validateRow(row, i + 1);
        }
    }

    public static void validateRow(ReportMonitoringDevice row, int number) {
        check(row.getName(), 255, "名称", number);
        check(row.getModel(), 128, "型号", number);
        check(row.getAccuracy(), 64, "精度", number);
        check(row.getMeasurementRange(), 64, "量程", number);
        check(row.getLocation(), 255, "安装位置", number);
        check(row.getCalibrationFrequency(), 64, "检定周期", number);
        check(row.getSourceTable(), 64, "来源表", number);
        check(row.getSourceId(), 64, "来源编号", number);
    }

    private static void check(String value, int max, String label, int row) {
        if (value != null && value.codePointCount(0, value.length()) > max)
            throw new ServiceException("监测设备第" + row + "行：" + label + "超过" + max + "字，请修改后保存", HttpStatus.BAD_REQUEST);
    }
}
