package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.util.List;
import java.util.Map;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.mapper.ReportMonitoringDeviceMapper;
import com.ruoyi.common.core.exception.ServiceException;

class ReportMonitoringImportTest {
    @Test void parserAndMergerPreserveDistinctRowsWithoutNamesAsKeys() {
        var rows = ReportExcelParser.toMonitoring(List.of(Map.of("name", "电表", "model", "A"),
                Map.of("name", "电表", "model", "A"), Map.of("name", "", "location", "2#进线"), Map.of()));
        assertEquals(3, rows.size());
        assertEquals("", rows.get(2).getName());
        assertEquals(6, ReportExcelMerger.mergeMonitoring(rows, rows, false).size());
        assertEquals(3, ReportExcelMerger.mergeMonitoring(rows, rows, true).size());
    }

    @Test void oldImportEndpointAlsoAcceptsSameNameAndExactDuplicateDevices() throws Exception {
        var service = new ReportExcelImportService();
        var mapper = mock(ReportMonitoringDeviceMapper.class);
        ReflectionTestUtils.setField(service, "monitoringMapper", mapper);
        ReportMonitoringDevice saved = new ReportMonitoringDevice(); saved.setName("电表");
        when(mapper.selectByReport(9L, 3030L)).thenReturn(List.of(saved));
        ReportTask task = new ReportTask(); task.setId(9L); task.setDeptId(3030L);
        try (var book = new XSSFWorkbook(); var output = new ByteArrayOutputStream()) {
            var sheet = book.createSheet();
            sheet.createRow(0).createCell(0).setCellValue("名称");
            sheet.createRow(1).createCell(0).setCellValue("电表");
            sheet.createRow(2).createCell(0).setCellValue("电表");
            book.write(output);
            service.apply(task, ReportExcelType.monitoring, false, new ByteArrayInputStream(output.toByteArray()), "admin");
        }
        verify(mapper).deleteByReport(9L, 3030L);
        verify(mapper, times(3)).insert(any());
    }

    @Test void storageLengthCountsCharactersAndDoesNotTruncate() {
        ReportMonitoringDevice row = new ReportMonitoringDevice(); row.setName("");
        row.setMeasurementRange("😀".repeat(64));
        ReportMonitoringRules.validateLengths(List.of(row));
        row.setMeasurementRange("测".repeat(65));
        assertThrows(ServiceException.class, () -> ReportMonitoringRules.validateLengths(List.of(row)));
        assertEquals(65, row.getMeasurementRange().length());
    }
}
