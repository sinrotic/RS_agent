package com.sinrotic.rs.user.exception;

/**
 * Base runtime exception for user-service business failures.
 */
public class UserServiceException extends RuntimeException {

    public UserServiceException(String message) {
        super(message);
    }
}
