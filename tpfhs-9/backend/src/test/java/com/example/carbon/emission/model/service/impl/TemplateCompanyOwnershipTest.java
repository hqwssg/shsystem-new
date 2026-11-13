package com.example.carbon.emission.model.service.impl;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import java.util.*;
import java.time.LocalDate;
import org.junit.jupiter.api.*;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.*;
import org.springframework.web.server.ResponseStatusException;
import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.*;
import com.example.carbon.emission.model.security.*;
import com.example.carbon.emission.model.dto.CreateTemplateRequest;

class TemplateCompanyOwnershipTest {
    @AfterEach void clear() { RequestContextHolder.resetRequestAttributes(); }
    private void context(boolean all, boolean self, List<Long> departments, Set<String> perms) {
        MockHttpServletRequest request=new MockHttpServletRequest();
        request.setAttribute(CarbonSecurityContext.REQUEST_ATTRIBUTE,new CarbonSecurityContext(8L,"admin","Admin",3000L,"HQ",Set.of(),perms,all,self,departments,List.of()));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
    }
    private CompanyOwnershipService companies() {
        return new CompanyOwnershipService(mock(JdbcTemplate.class)) {
            @Override public List<Company> registered() { return List.of(new Company(302L,"A"),new Company(303L,"B")); }
        };
    }

    @Test void ExistingPermissionScopeFiltersRegisteredCompaniesWithoutPromotingChildDepartment() {
        CompanyOwnershipService service=companies();
        context(false,false,List.of(302L),Set.of("carbon:model:edit"));assertEquals(302L,service.require(302L));assertThrows(ResponseStatusException.class,()->service.require(303L));
        context(false,false,List.of(3021L),Set.of("carbon:model:edit"));assertTrue(service.options().isEmpty());
        context(false,true,List.of(302L),Set.of("carbon:model:edit"));assertTrue(service.options().isEmpty());
        context(true,false,List.of(),Set.of("carbon:model:view"));assertThrows(ResponseStatusException.class,service::options);
        context(true,false,List.of(),Set.of("carbon:model:edit"));assertEquals(2,service.options().size());assertThrows(ResponseStatusException.class,()->service.require(999L));
    }

    private TemplateServiceImpl service(TemplateRepository templates, JdbcTemplate jdbc) {
        TemplateServiceImpl service=new TemplateServiceImpl();ReflectionTestUtils.setField(service,"templateRepository",templates);
        ReflectionTestUtils.setField(service,"companies",companies());ReflectionTestUtils.setField(service,"jdbc",jdbc);
        ReflectionTestUtils.setField(service,"entityManager",mock(jakarta.persistence.EntityManager.class));
        ReflectionTestUtils.setField(service,"dataScope",mock(CarbonDataScopeService.class));
        ReflectionTestUtils.setField(service,"userRepository",mock(UserRepository.class));return service;
    }

    @Test void HeadquartersCreatorChoosesActualCompanyRatherThanOwnDepartment() {
        context(true,false,List.of(),Set.of("carbon:model:edit"));TemplateRepository repo=mock(TemplateRepository.class);TemplateServiceImpl service=service(repo,mock(JdbcTemplate.class));
        when(repo.save(any())).thenAnswer(c->c.getArgument(0));CreateTemplateRequest request=new CreateTemplateRequest();request.setName("Company A");request.setCreatedBy(8L);request.setTemplateType(2);
        assertThrows(ResponseStatusException.class,()->service.createTemplate(request));verify(repo,never()).save(any());
        request.setCompanyDeptId(302L);assertEquals(302L,service.createTemplate(request).getDeptId());
    }

    @Test void LegacyConfirmationIsExplicitAndNeverOverwritesFrozenOwnership() {
        context(true,false,List.of(),Set.of("carbon:model:edit"));TemplateRepository repo=mock(TemplateRepository.class);JdbcTemplate jdbc=mock(JdbcTemplate.class);TemplateServiceImpl service=service(repo,jdbc);
        Template template=new Template();template.setId(1L);template.setDeptId(3000L);when(repo.findForCompanyUpdate(1L)).thenReturn(Optional.of(template));when(repo.save(any())).thenAnswer(c->c.getArgument(0));
        service.assignCompany(1L,302L,false);verify(jdbc,never()).update(anyString(),any(Object[].class));
        service.assignCompany(1L,302L,true);verify(jdbc).update(contains("company_dept_id is null"),eq(302L),eq(8L),eq(1L));
        when(jdbc.queryForObject(contains("company_dept_id<>?"),eq(Integer.class),eq(1L),eq(303L))).thenReturn(1);
        assertThrows(ResponseStatusException.class,()->service.assignCompany(1L,303L,true));assertEquals(302L,template.getDeptId());
    }

    @Test void ActiveTaskOrMissingTemplateAuthorityBlocksOwnershipChange() {
        context(true,false,List.of(),Set.of("carbon:model:edit"));TemplateRepository repo=mock(TemplateRepository.class);JdbcTemplate jdbc=mock(JdbcTemplate.class);TemplateServiceImpl service=service(repo,jdbc);
        Template template=new Template();template.setId(1L);when(repo.findForCompanyUpdate(1L)).thenReturn(Optional.of(template));
        when(jdbc.queryForObject(contains("status in (0,1)"),eq(Integer.class),eq(1L))).thenReturn(1);
        assertThrows(ResponseStatusException.class,()->service.assignCompany(1L,302L,true));verify(jdbc,never()).update(anyString(),any(Object[].class));
        CarbonDataScopeService scope=mock(CarbonDataScopeService.class);ReflectionTestUtils.setField(service,"dataScope",scope);
        doThrow(new ResponseStatusException(org.springframework.http.HttpStatus.FORBIDDEN)).when(scope).requireTemplate(1L,true);
        assertThrows(ResponseStatusException.class,()->service.assignCompany(1L,302L,false));
    }

    @Test void ReservationFreezesCompanyInTheSameTransactionAsTaskCreation() {
        CalculationTemplateRepository repo=mock(CalculationTemplateRepository.class);TemplateRepository templates=mock(TemplateRepository.class);
        CalculationTaskReservationService service=new CalculationTaskReservationService(repo);ReflectionTestUtils.setField(service,"templates",templates);ReflectionTestUtils.setField(service,"companies",companies());
        Template template=new Template();template.setDeptId(302L);when(templates.findForCompanyUpdate(1L)).thenReturn(Optional.of(template));when(repo.saveAndFlush(any())).thenAnswer(c->c.getArgument(0));
        CalculationTemplate task=service.reserve(1L,LocalDate.of(2025,1,1),LocalDate.of(2025,12,31),0L);assertEquals(302L,task.getCompanyDeptId());
        template.setDeptId(303L);assertEquals(302L,task.getCompanyDeptId());
        template.setDeptId(3000L);
        assertThrows(ResponseStatusException.class,()->service.reserve(1L,LocalDate.of(2026,1,1),LocalDate.of(2026,12,31),0L));
        verify(repo,times(1)).saveAndFlush(any());
    }
}
