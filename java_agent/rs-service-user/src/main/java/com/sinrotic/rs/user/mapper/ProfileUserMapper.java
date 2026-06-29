package com.sinrotic.rs.user.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * MyBatis mapper for review users sourced from amazon_reviews_base.
 */
@Mapper
public interface ProfileUserMapper {

    boolean existsReviewUser(@Param("profileUserId") String profileUserId);

    String selectRandomReviewUserId();
}
