package com.example.carbon.emission.model.security;

import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class RuoYiSecurityClient {
    private final RestClient restClient;
    private final CarbonSecurityProperties properties;

    public RuoYiSecurityClient(RestClient.Builder builder, CarbonSecurityProperties properties) {
        this.restClient = builder.build();
        this.properties = properties;
    }

    public CarbonSecurityContext load(String authorization) {
        return loadContext(authorization, null);
    }

    public CarbonSecurityContext loadScoped(String authorization, String permission) {
        return loadContext(authorization, permission);
    }

    private CarbonSecurityContext loadContext(String authorization, String permission) {
        String endpoint = permission == null ? properties.getEndpoint()
                : org.springframework.web.util.UriComponentsBuilder.fromUriString(properties.getEndpoint())
                    .queryParam("permission", permission).build().toUriString();
        Map<String, Object> response = restClient.get()
                .uri(endpoint)
                .header(HttpHeaders.AUTHORIZATION, authorization)
                .retrieve()
                .body(new ParameterizedTypeReference<>() {});
        int code = response == null ? -1 : number(response.get("code"));
        if (code == 401 || code == 403) {
            throw new HttpClientErrorException(HttpStatus.valueOf(code), "RuoYi rejected the current login session");
        }
        if (code != 200 || !(response.get("data") instanceof Map<?, ?> data)
                || longValue(data.get("userId")) == null || longValue(data.get("userId")) <= 0) {
            throw new IllegalStateException("Invalid RuoYi security context response");
        }
        if (permission != null && !permission.equals(data.get("scopePermission")))
            throw new IllegalStateException("RuoYi has not supplied operation-specific scope");
        return new CarbonSecurityContext(
                longValue(data.get("userId")),
                text(data.get("userName")),
                text(data.get("nickName")),
                longValue(data.get("deptId")),
                text(data.get("deptName")),
                strings(data.get("roles")),
                strings(data.get("permissions")),
                Boolean.TRUE.equals(data.get("allData")),
                Boolean.TRUE.equals(data.get("selfOnly")),
                longs(data.get("deptIds")),
                longs(data.get("nodeIds")));
    }

    private int number(Object value) {
        return value instanceof Number number ? number.intValue() : -1;
    }

    private Long longValue(Object value) {
        return value instanceof Number number ? number.longValue() : null;
    }

    private String text(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private Set<String> strings(Object value) {
        if (!(value instanceof Iterable<?> values)) {
            return Collections.emptySet();
        }
        return java.util.stream.StreamSupport.stream(values.spliterator(), false)
                .map(String::valueOf)
                .collect(Collectors.toUnmodifiableSet());
    }

    private List<Long> longs(Object value) {
        if (!(value instanceof Iterable<?> values)) {
            return List.of();
        }
        return java.util.stream.StreamSupport.stream(values.spliterator(), false)
                .filter(Number.class::isInstance)
                .map(Number.class::cast)
                .map(Number::longValue)
                .toList();
    }
}
