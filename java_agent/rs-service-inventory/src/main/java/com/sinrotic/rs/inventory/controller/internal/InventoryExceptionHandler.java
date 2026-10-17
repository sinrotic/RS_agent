package com.sinrotic.rs.inventory.controller.internal;

import com.sinrotic.rs.inventory.service.InventoryServiceException;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import java.util.Map;

@RestControllerAdvice
public class InventoryExceptionHandler {
    @ExceptionHandler(InventoryServiceException.class)
    @ResponseStatus(HttpStatus.CONFLICT)
    public Map<String, String> conflict(InventoryServiceException exception) {
        return Map.of("message", exception.getMessage());
    }
}
