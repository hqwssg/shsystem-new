package com.ruoyi.carbon.report.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;
import com.ruoyi.carbon.report.domain.ReportDeptProfile;
import com.ruoyi.carbon.report.mapper.ReportDeptProfileMapper;

class ReportDeptProfileServiceImplTest
{
    @Test
    void saveActivityProseUpdatesOnlyJson()
    {
        ReportDeptProfileMapper mapper = mock(ReportDeptProfileMapper.class);
        ReportDeptProfile existing = new ReportDeptProfile();
        existing.setDeptId(301L);
        existing.setLegalName("肃宁分公司");
        when(mapper.selectByDeptId(301L)).thenReturn(existing);
        ReportDeptProfileServiceImpl service = new ReportDeptProfileServiceImpl();
        ReflectionTestUtils.setField(service, "profileMapper", mapper);
        service.saveActivityProse(301L, "{\"natural_gas\":{\"usage\":\"食堂灶具\",\"bogus\":\"x\"}}", "admin");
        verify(mapper).updateActivityProse(eq(301L), any(), eq("admin"));
        verify(mapper, org.mockito.Mockito.never()).update(any());
    }

    @Test
    void saveActivityProseInsertsWhenMissing()
    {
        ReportDeptProfileMapper mapper = mock(ReportDeptProfileMapper.class);
        when(mapper.selectByDeptId(301L)).thenReturn(null).thenReturn(new ReportDeptProfile());
        ReportDeptProfileServiceImpl service = new ReportDeptProfileServiceImpl();
        ReflectionTestUtils.setField(service, "profileMapper", mapper);
        service.saveActivityProse(301L, "{\"natural_gas\":{\"usage\":\"食堂灶具\"}}", "admin");
        ArgumentCaptor<ReportDeptProfile> captor = ArgumentCaptor.forClass(ReportDeptProfile.class);
        verify(mapper).insert(captor.capture());
        assertEquals(301L, captor.getValue().getDeptId());
        assertEquals("admin", captor.getValue().getCreateBy());
    }
}
