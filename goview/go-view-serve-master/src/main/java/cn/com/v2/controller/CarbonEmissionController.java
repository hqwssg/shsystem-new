package cn.com.v2.controller;

import java.util.Map;

import javax.servlet.http.HttpServletRequest;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import cn.com.v2.common.domain.AjaxResult;

/** Proxies the authoritative model statistics API for GoView data sources. */
@RestController
public class CarbonEmissionController {

	private final RestTemplate restTemplate = new RestTemplate();

	@Value("${carbon.statistics.base-url:http://127.0.0.1:8082/api/emission-data}")
	private String statisticsBaseUrl;

	@GetMapping("/carbon/surface")
	public AjaxResult surface(@RequestParam(value = "granularity", defaultValue = "month") String granularity,
			@RequestParam(value = "templateId", required = false) Long templateId,
			@RequestParam(value = "energyType", required = false) Integer energyType,
			HttpServletRequest request) {
		UriComponentsBuilder uri = UriComponentsBuilder.fromHttpUrl(statisticsBaseUrl + "/surface")
				.queryParam("granularity", granularity);
		if (templateId != null) uri.queryParam("templateId", templateId);
		if (energyType != null) uri.queryParam("energyType", energyType);
		return fetch(uri, request);
	}

	@GetMapping("/carbon/dashboard")
	public AjaxResult dashboard(@RequestParam Map<String, String> parameters, HttpServletRequest request) {
		UriComponentsBuilder uri = UriComponentsBuilder.fromHttpUrl(statisticsBaseUrl + "/dashboard");
		parameters.forEach(uri::queryParam);
		return fetch(uri, request);
	}

	@GetMapping("/carbon/segment-energy")
	public AjaxResult segmentEnergy(HttpServletRequest request) {
		return fetch(UriComponentsBuilder.fromHttpUrl(statisticsBaseUrl + "/segment-energy"), request);
	}

	private AjaxResult fetch(UriComponentsBuilder uri, HttpServletRequest request) {
		String authorization = request.getHeader(HttpHeaders.AUTHORIZATION);
		HttpHeaders headers = new HttpHeaders();
		if (authorization != null) headers.set(HttpHeaders.AUTHORIZATION, authorization);
		try {
			ResponseEntity<Object> response = restTemplate.exchange(
					uri.build(true).toUri(), HttpMethod.GET, new HttpEntity<Object>(headers), Object.class);
			return AjaxResult.successData(200, response.getBody());
		}
		catch (RestClientException ex)
		{
			return AjaxResult.error(502, "碳排放统计服务暂不可用");
		}
	}
}
