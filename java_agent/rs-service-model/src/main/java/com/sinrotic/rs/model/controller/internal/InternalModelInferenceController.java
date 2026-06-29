package com.sinrotic.rs.model.controller.internal;

import com.sinrotic.rs.model.domain.dto.ModelInferRequestDTO;
import com.sinrotic.rs.model.domain.vo.ModelInferVO;
import com.sinrotic.rs.model.service.ModelGatewayService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/model")
public class InternalModelInferenceController {

    private final ModelGatewayService modelGatewayService;

    public InternalModelInferenceController(ModelGatewayService modelGatewayService) {
        this.modelGatewayService = modelGatewayService;
    }

    @PostMapping("/infer")
    public ModelInferVO infer(@RequestBody ModelInferRequestDTO request) {
        return modelGatewayService.infer(request);
    }
}
