package com.sinrotic.rs.gateway.filter;

import io.netty.util.NetUtil;
import java.net.InetAddress;
import java.time.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;

/** 只信任明确配置的地址或 DNS 名称；容器地址变化后重新解析，失败时拒绝转发身份。 */
final class TrustedProxyResolver {
    private record Resolution(Set<String> addresses, Instant expiresAt) { }
    private final Set<String> literals;
    private final Set<String> hostnames;
    private final Map<String,Resolution> cache = new ConcurrentHashMap<>();
    private final Clock clock;
    private final Function<String,Set<String>> lookup;

    TrustedProxyResolver(Set<String> entries,Clock clock) {
        this(entries,clock,hostname -> {
            try {
                var result = new HashSet<String>();
                for (var address : InetAddress.getAllByName(hostname)) result.add(address.getHostAddress());
                return Set.copyOf(result);
            } catch (java.net.UnknownHostException ignored) { return Set.of(); }
        });
    }

    TrustedProxyResolver(Set<String> entries,Clock clock,Function<String,Set<String>> lookup) {
        var literalEntries = new HashSet<String>();var names = new HashSet<String>();
        for (String entry : entries) {
            String value = entry.trim();
            if (numericAddress(value)) literalEntries.add(normalize(value));
            else if (!value.isBlank()) names.add(value);
        }
        this.literals = Set.copyOf(literalEntries);this.hostnames = Set.copyOf(names);
        this.clock = clock;this.lookup = lookup;
    }

    boolean requiresLookup() { return !hostnames.isEmpty(); }

    boolean trusted(String address) {
        String normalized = normalize(address);
        if (literals.contains(normalized)) return true;
        for (String hostname : hostnames) {
            var resolution = cache.compute(hostname,(key,current) -> {
                if (current != null && current.expiresAt().isAfter(clock.instant())) return current;
                Set<String> addresses;
                try { addresses = lookup.apply(key).stream().map(TrustedProxyResolver::normalize)
                        .collect(java.util.stream.Collectors.toUnmodifiableSet()); }
                catch (RuntimeException ignored) { addresses = Set.of(); }
                return new Resolution(addresses,clock.instant().plusSeconds(30));
            });
            if (resolution.addresses().contains(normalized)) return true;
        }
        return false;
    }

    static boolean numericAddress(String value) {
        return NetUtil.isValidIpV4Address(value) || NetUtil.isValidIpV6Address(value);
    }

    static String normalize(String value) {
        if (!numericAddress(value)) return value;
        try { return InetAddress.getByName(value).getHostAddress(); }
        catch (java.net.UnknownHostException ignored) { return value; }
    }
}
