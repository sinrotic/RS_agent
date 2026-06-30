package com.sinrotic.rs.order.service;

import org.springframework.stereotype.Component;

import java.util.concurrent.atomic.AtomicLong;

@Component
public class AtomicLongIdGenerator implements IdGenerator {

    private final AtomicLong sequence = new AtomicLong(System.currentTimeMillis());

    @Override
    public long nextId() {
        return sequence.incrementAndGet();
    }
}
