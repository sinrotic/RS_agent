package com.sinrotic.rs.seckill.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.scripting.support.ResourceScriptSource;

@Configuration
public class SeckillRedisScriptConfig {

    @Bean
    public DefaultRedisScript<Long> seckillPreDeductScript() {
        DefaultRedisScript<Long> script = new DefaultRedisScript<>();
        script.setScriptSource(new ResourceScriptSource(new ClassPathResource("lua/seckill_pre_deduct.lua")));
        script.setResultType(Long.class);
        return script;
    }
}
