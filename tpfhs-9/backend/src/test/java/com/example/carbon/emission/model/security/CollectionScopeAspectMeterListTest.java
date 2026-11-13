package com.example.carbon.emission.model.security;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.reflect.MethodSignature;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import org.springframework.web.servlet.HandlerMapping;

import com.example.carbon.emission.model.controller.FossilFuelCollectionController;
import com.example.carbon.emission.model.controller.PurchasedHeatCollectionController;
import com.example.carbon.emission.model.entity.FossilFuelMeterInfo;
import com.example.carbon.emission.model.entity.PurchasedHeatMeterInfo;
import com.fasterxml.jackson.databind.ObjectMapper;

class CollectionScopeAspectMeterListTest
{
    @AfterEach
    void clearRequest()
    {
        RequestContextHolder.resetRequestAttributes();
    }

    @Test
    void fossilCollectionPointSelectionFiltersReturnedRowsAsMeters() throws Throwable
    {
        FossilFuelMeterInfo meter = new FossilFuelMeterInfo();
        meter.setId(41L);
        Method method = FossilFuelCollectionController.class.getMethod(
                "listMetersForCollectionPointSelection", Long.class);

        assertMeterFiltering(new FossilFuelCollectionController(), method, new Object[] { 5L },
                "/api/fossil-fuel-collection/sub-scopes/5/meters", Map.of("subScopeId", "5"),
                ResponseEntity.ok(List.of(meter)), "fossil", 41L);
    }

    @Test
    void heatCollectionPointSelectionFiltersReturnedRowsAsMeters() throws Throwable
    {
        PurchasedHeatMeterInfo meter = new PurchasedHeatMeterInfo();
        meter.setId(42L);
        Method method = PurchasedHeatCollectionController.class.getMethod(
                "listMetersForCollectionPointSelection", Long.class);

        assertMeterFiltering(new PurchasedHeatCollectionController(), method, new Object[] { 6L },
                "/api/purchased-heat-collection/sub-scopes/6/meters", Map.of("subScopeId", "6"),
                ResponseEntity.ok(List.of(meter)), "heat", 42L);
    }

    private static void assertMeterFiltering(Object controller, Method method, Object[] args, String path,
            Map<String, String> variables, ResponseEntity<?> response, String type, Long meterId) throws Throwable
    {
        CollectionScopeService scopes = mock(CollectionScopeService.class);
        when(scopes.isAllowed(type, "meter", meterId, false)).thenReturn(true);
        CollectionScopeAspect aspect = new CollectionScopeAspect(scopes, new ObjectMapper());

        ProceedingJoinPoint point = mock(ProceedingJoinPoint.class);
        MethodSignature signature = mock(MethodSignature.class);
        when(point.getTarget()).thenReturn(controller);
        when(point.getSignature()).thenReturn(signature);
        when(signature.getMethod()).thenReturn(method);
        when(point.getArgs()).thenReturn(args);
        when(point.proceed()).thenReturn(response);

        MockHttpServletRequest request = new MockHttpServletRequest("GET", path);
        request.setAttribute(HandlerMapping.URI_TEMPLATE_VARIABLES_ATTRIBUTE, variables);
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));

        ResponseEntity<?> filtered = (ResponseEntity<?>) aspect.check(point);

        assertEquals(1, ((List<?>) filtered.getBody()).size());
        verify(scopes).require(type, "sub_scope", Long.valueOf(variables.get("subScopeId")), false);
        verify(scopes).isAllowed(type, "meter", meterId, false);
        verify(scopes, never()).isAllowed(type, "sub_scope", meterId, false);
    }
}
