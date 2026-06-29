package com.sinrotic.rs.user.domain.dto;

import java.util.List;

/**
 * Request body for batch internal user-context queries.
 */
public record BatchUserContextRequestDTO(
        List<String> accountIds,
        List<String> profileUserIds
) {
}
