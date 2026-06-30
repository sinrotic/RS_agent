package com.sinrotic.rs.inventory.service;

public class InventoryServiceException extends IllegalStateException {

    public InventoryServiceException(String message) {
        super(message);
    }

    public InventoryServiceException(String message, Throwable cause) {
        super(message, cause);
    }
}
