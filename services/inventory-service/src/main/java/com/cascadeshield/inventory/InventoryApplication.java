package com.cascadeshield.inventory;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

// scanBasePackages: com.cascadeshield.common holds the shared RestTemplateConfig/
// GlobalExceptionHandler beans (cascadeshield-common module) -- without this, Spring
// Boot's default component scan (this class's own package + sub-packages only) would
// never find them, since they now live outside com.cascadeshield.inventory.
@SpringBootApplication(scanBasePackages = {"com.cascadeshield.inventory", "com.cascadeshield.common"})
public class InventoryApplication {
    public static void main(String[] args) {
        SpringApplication.run(InventoryApplication.class, args);
    }
}
