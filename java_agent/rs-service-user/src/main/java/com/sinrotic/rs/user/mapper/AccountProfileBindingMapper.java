package com.sinrotic.rs.user.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * MyBatis mapper for account-to-profile-user bindings.
 */
@Mapper
public interface AccountProfileBindingMapper {

    String findActiveProfileUserIdByAccountId(@Param("accountId") String accountId);

    int insertBinding(
            @Param("bindingId") String bindingId,
            @Param("accountId") String accountId,
            @Param("profileUserId") String profileUserId,
            @Param("bindingStrategy") String bindingStrategy,
            @Param("segment") String segment
    );
}
