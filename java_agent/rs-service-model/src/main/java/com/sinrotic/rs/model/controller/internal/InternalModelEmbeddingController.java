package com.sinrotic.rs.model.controller.internal;

import com.sinrotic.rs.model.domain.dto.ModelEmbedRequestDTO;
import com.sinrotic.rs.model.domain.vo.ModelEmbedVO;
import com.sinrotic.rs.model.service.ModelGatewayService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/model")
public class InternalModelEmbeddingController {

    private final ModelGatewayService modelGatewayService;

    public InternalModelEmbeddingController(ModelGatewayService modelGatewayService) {
        this.modelGatewayService = modelGatewayService;
    }

    @PostMapping("/embed")
    public ModelEmbedVO embed(@RequestBody ModelEmbedRequestDTO request) {
        return modelGatewayService.embed(request);
    }
}
