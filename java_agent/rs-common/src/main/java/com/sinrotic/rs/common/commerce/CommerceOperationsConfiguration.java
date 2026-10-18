package com.sinrotic.rs.common.commerce;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** 运维只读与写入凭证分离；缺少配置时拒绝运维访问，不影响服务间业务调用。 */
@Configuration(proxyBeanMethods=false)
public class CommerceOperationsConfiguration {
    private static final String ACTOR="commerce.authenticatedOperator";
    @Bean
    public FilterRegistrationBean<OperationsFilter> commerceOperationsFilter(
            @Value("${rs.commerce.operations.read-token:}") String readToken,
            @Value("${rs.commerce.operations.write-token:}") String writeToken,
            @Value("${rs.commerce.operations.operator-id:commerce-operator}") String operatorId) {
        var registration=new FilterRegistrationBean<>(new OperationsFilter(readToken,writeToken,operatorId));
        registration.addUrlPatterns("/internal/*");registration.setOrder(-100);
        return registration;
    }
    public static String actor(HttpServletRequest request) {
        if(!(request.getAttribute(ACTOR) instanceof String actor)) throw new ResponseStatusException(HttpStatus.FORBIDDEN,"需要经过认证的运维身份");
        return actor;
    }
    public static final class OperationsFilter extends OncePerRequestFilter {
        private final String readToken,writeToken,operatorId;
        public OperationsFilter(String readToken,String writeToken,String operatorId) {
            if((!readToken.isEmpty() && readToken.length()<32) || (!writeToken.isEmpty() && writeToken.length()<32))
                throw new IllegalArgumentException("运维凭证至少需要 32 个字符");
            if(!readToken.isEmpty() && readToken.equals(writeToken)) throw new IllegalArgumentException("只读与写入凭证必须不同");
            if(operatorId.isBlank() || operatorId.length()>64 || !operatorId.equals(operatorId.trim())) throw new IllegalArgumentException("运维身份标识不合法");
            this.readToken=readToken;this.writeToken=writeToken;this.operatorId=operatorId;
        }
        @Override protected boolean shouldNotFilter(HttpServletRequest request) {
            String path=request.getServletPath();
            if(path.isEmpty()) path=request.getRequestURI().substring(request.getContextPath().length());
            return !path.matches("/internal/(checkout/(tasks|refunds|events|offers)|payment/notifications|seckill/(tasks|allocations|activities)|inventory/management|promotions/campaigns)(/.*)?");
        }
        @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain) throws ServletException,IOException {
            String header=request.getHeader("Authorization");
            String token=header!=null && header.startsWith("Bearer ") ? header.substring(7) : "";
            boolean writer=matches(writeToken,token),reader=matches(readToken,token);
            if(!writer && !reader) {response.sendError(401,"需要运维凭证");return;}
            if(!request.getMethod().equals("GET") && !writer) {response.sendError(403,"只读运维身份不能修改任务");return;}
            request.setAttribute(ACTOR,writer ? operatorId : "commerce-reader");
            chain.doFilter(request,response);
        }
        private static boolean matches(String configured,String provided) {
            return !configured.isEmpty() && MessageDigest.isEqual(configured.getBytes(StandardCharsets.UTF_8),provided.getBytes(StandardCharsets.UTF_8));
        }
    }
}
