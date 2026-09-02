package com.cascadeshield.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

// scanBasePackages: com.cascadeshield.common holds the shared RestTemplateConfig/
// GlobalExceptionHandler beans (cascadeshield-common module) -- without this, Spring
// Boot's default component scan (this class's own package + sub-packages only) would
// never find them, since they now live outside com.cascadeshield.gateway.
@SpringBootApplication(scanBasePackages = {"com.cascadeshield.gateway", "com.cascadeshield.common"})
public class GatewayApplication {
    public static void main(String[] args) {
        SpringApplication.run(GatewayApplication.class, args);
    }
}
