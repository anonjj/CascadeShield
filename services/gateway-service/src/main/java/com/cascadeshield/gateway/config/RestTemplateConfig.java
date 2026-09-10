package com.cascadeshield.gateway.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RestTemplateConfig {

    @Bean
    public RestTemplate restTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(3_000); // 3 seconds to connect to the downstream service
        // 8s read timeout: long enough for ~3s latency fault to complete (counted as
        // slow call by CB)
        factory.setReadTimeout(8_000); // 8 seconds to read the response from the downstream service
        return new RestTemplate(factory);
    }
}
