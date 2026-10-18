package com.sinrotic.rs.common.commerce;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;

public final class CommerceInput {
    public record Page<T>(List<T> items,String nextCursor) {}
    public static String id(String value) {
        if(value==null || value.isBlank() || value.length()>64 || !value.equals(value.trim())) throw bad("标识不合法");
        return value;
    }
    public static String reason(String value) {
        if(value==null || value.isBlank() || value.length()>255) throw bad("请提供不超过255字符的原因");return value.trim();
    }
    public static int limit(int limit) {if(limit<1 || limit>100) throw bad("分页大小须为1至100");return limit;}
    public static ResponseStatusException bad(String message) {return new ResponseStatusException(HttpStatus.BAD_REQUEST,message);}
    public static ResponseStatusException conflict(String message) {return new ResponseStatusException(HttpStatus.CONFLICT,message);}
    public static ResponseStatusException missing(String message) {return new ResponseStatusException(HttpStatus.NOT_FOUND,message);}
    private CommerceInput() {}
}
