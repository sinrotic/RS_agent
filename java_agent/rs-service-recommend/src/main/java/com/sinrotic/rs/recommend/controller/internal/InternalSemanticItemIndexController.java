package com.sinrotic.rs.recommend.controller.internal;

import com.sinrotic.rs.recommend.domain.dto.SemanticItemIndexRebuildRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.SemanticItemIndexResultVO;
import com.sinrotic.rs.recommend.service.SemanticItemIndexService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/recommend/semantic-item-index")
public class InternalSemanticItemIndexController {

    private final SemanticItemIndexService semanticItemIndexService;

    public InternalSemanticItemIndexController(SemanticItemIndexService semanticItemIndexService) {
        this.semanticItemIndexService = semanticItemIndexService;
    }

    @PostMapping("/rebuild")
    public SemanticItemIndexResultVO rebuild(@RequestBody SemanticItemIndexRebuildRequestDTO request) {
        SemanticItemIndexRebuildRequestDTO normalized = request.withDefaults();
        return semanticItemIndexService.rebuild(
                normalized.requestId(),
                normalized.pageSize(),
                normalized.maxPages()
        );
    }
}
