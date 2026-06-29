package com.sinrotic.rs.model;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Entry point for the model gateway microservice.
 */
@SpringBootApplication
public class ModelServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(ModelServiceApplication.class, args);
    }
}
