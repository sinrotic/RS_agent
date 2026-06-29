package com.sinrotic.rs.model.controller.internal;

import com.sinrotic.rs.model.domain.dto.ModelRankRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelRankSignalsRequestDTO;
import com.sinrotic.rs.model.domain.vo.ModelRankSignalsVO;
import com.sinrotic.rs.model.domain.vo.ModelRankVO;
import com.sinrotic.rs.model.service.ModelGatewayService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/model")
public class InternalModelRankingController {

    private final ModelGatewayService modelGatewayService;

    public InternalModelRankingController(ModelGatewayService modelGatewayService) {
        this.modelGatewayService = modelGatewayService;
    }

    @PostMapping("/rank")
    public ModelRankVO rank(@RequestBody ModelRankRequestDTO request) {
        return modelGatewayService.rank(request);
    }

    @PostMapping("/rank-signals")
    public ModelRankSignalsVO rankSignals(@RequestBody ModelRankSignalsRequestDTO request) {
        return modelGatewayService.rankSignals(request);
    }
}
