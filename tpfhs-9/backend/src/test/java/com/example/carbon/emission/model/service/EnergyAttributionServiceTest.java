package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.entity.DataDict;
import com.example.carbon.emission.model.entity.DataDictItem;
import com.example.carbon.emission.model.entity.EnergyAttributionStation;
import com.example.carbon.emission.model.repository.*;
import com.example.carbon.emission.model.security.CarbonSecurityContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class EnergyAttributionServiceTest {
    @Mock EnergyAttributionStationRepository stations;
    @Mock DataDictRepository dicts;
    @Mock DataDictItemRepository items;
    @Mock MeterInfoRepository electricity;
    @Mock FossilFuelMeterInfoRepository fossil;
    @Mock PurchasedHeatMeterInfoRepository heat;
    @Mock JdbcTemplate jdbc;
    EnergyAttributionService service;

    @BeforeEach
    void setUp() {
        service = new EnergyAttributionService(stations, dicts, items, electricity, fossil, heat, jdbc);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute(CarbonSecurityContext.REQUEST_ATTRIBUTE,
                new CarbonSecurityContext(7L, "tester", "tester", 10L, "测试部门", Set.of(), Set.of(), true, false, List.of(), List.of()));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
    }

    @AfterEach void clean() { RequestContextHolder.resetRequestAttributes(); }

    @Test
    void createsStationUsingDictionaryValuesAndGeneratedPinyin() {
        allowDict("shuohuang_railway_line", "朔黄线", 1L);
        allowDict("energy_allocation", "肃宁分公司", 2L);
        when(stations.countDuplicate(anyString(), anyString(), anyString(), isNull())).thenReturn(0L);
        when(stations.save(any())).thenAnswer(invocation -> invocation.getArgument(0));
        EnergyAttributionStation input = station("黄骅南站区", "朔黄线", "肃宁分公司");

        EnergyAttributionStation saved = service.createStation(input);

        assertThat(saved.getPinyinCode()).isEqualTo("HHNZQ");
        assertThat(saved.getCreatedBy()).isEqualTo(7L);
        assertThat(saved.getUpdatedBy()).isEqualTo(7L);
    }

    @Test
    void rejectsDuplicateBusinessKey() {
        allowDict("shuohuang_railway_line", "朔黄线", 1L);
        allowDict("energy_allocation", "肃宁分公司", 2L);
        when(stations.countDuplicate(anyString(), anyString(), anyString(), isNull())).thenReturn(1L);

        assertThatThrownBy(() -> service.createStation(station("黄骅南站区", "朔黄线", "肃宁分公司")))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        e -> assertThat(e.getStatusCode()).isEqualTo(HttpStatus.CONFLICT));
        verify(stations, never()).save(any());
    }

    @Test
    void refusesToDeleteReferencedStation() {
        when(stations.existsById(9L)).thenReturn(true);
        when(electricity.countByEnergyAttributionStationId(9L)).thenReturn(1L);
        when(fossil.countByEnergyAttributionStationId(9L)).thenReturn(2L);
        when(heat.countByEnergyAttributionStationId(9L)).thenReturn(0L);

        assertThatThrownBy(() -> service.deleteStation(9L))
                .isInstanceOfSatisfying(ResponseStatusException.class, e -> {
                    assertThat(e.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
                    assertThat(e.getReason()).contains("3个采集点");
                });
        verify(stations, never()).deleteById(anyLong());
    }

    private void allowDict(String code, String value, Long id) {
        DataDict dict = new DataDict(); dict.setId(id); dict.setDictCode(code);
        DataDictItem item = new DataDictItem(); item.setStatus(1); item.setItemValue(value);
        when(dicts.findByDictCode(code)).thenReturn(Optional.of(dict));
        when(items.findByDictIdAndItemValue(id, value)).thenReturn(Optional.of(item));
    }

    private EnergyAttributionStation station(String name, String line, String branch) {
        EnergyAttributionStation result = new EnergyAttributionStation();
        result.setName(name); result.setLineName(line); result.setBranchCompany(branch);
        return result;
    }
}
