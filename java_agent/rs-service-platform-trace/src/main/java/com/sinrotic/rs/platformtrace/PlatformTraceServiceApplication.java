package com.sinrotic.rs.platformtrace;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Entry point for the platform trace observation microservice.
 */
@SpringBootApplication
public class PlatformTraceServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(PlatformTraceServiceApplication.class, args);
    }
}
