package com.cascadeshield.payment;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

// scanBasePackages: com.cascadeshield.common holds the shared RestTemplateConfig/
// GlobalExceptionHandler beans (cascadeshield-common module) -- without this, Spring
// Boot's default component scan (this class's own package + sub-packages only) would
// never find them, since they now live outside com.cascadeshield.payment.
@SpringBootApplication(scanBasePackages = {"com.cascadeshield.payment", "com.cascadeshield.common"})
public class PaymentApplication {
    public static void main(String[] args) {
        SpringApplication.run(PaymentApplication.class, args);
    }
}
