package com.sinrotic.rs.user.mapper;

import com.sinrotic.rs.user.domain.entity.AuthAccountLoginRecord;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * MyBatis mapper for auth accounts.
 */
@Mapper
public interface AuthAccountMapper {

    int countByUsername(@Param("username") String username);

    AuthAccountLoginRecord findLoginAccountByUsername(@Param("username") String username);

    int insertAccount(
            @Param("accountId") String accountId,
            @Param("username") String username,
            @Param("passwordHash") String passwordHash,
            @Param("nickname") String nickname,
            @Param("avatarUrl") String avatarUrl
    );
}
