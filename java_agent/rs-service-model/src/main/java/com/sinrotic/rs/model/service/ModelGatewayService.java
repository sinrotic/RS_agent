package com.sinrotic.rs.model.service;

import com.sinrotic.rs.model.domain.dto.ModelChatRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelEmbedRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelInferRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelRankRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelRankSignalsRequestDTO;
import com.sinrotic.rs.model.domain.vo.ModelChatVO;
import com.sinrotic.rs.model.domain.vo.ModelChatStreamEventVO;
import com.sinrotic.rs.model.domain.vo.ModelEmbedVO;
import com.sinrotic.rs.model.domain.vo.ModelInferVO;
import com.sinrotic.rs.model.domain.vo.ModelRankSignalsVO;
import com.sinrotic.rs.model.domain.vo.ModelRankVO;

import java.util.List;

public interface ModelGatewayService {

    ModelInferVO infer(ModelInferRequestDTO request);

    ModelEmbedVO embed(ModelEmbedRequestDTO request);

    ModelRankVO rank(ModelRankRequestDTO request);

    ModelRankSignalsVO rankSignals(ModelRankSignalsRequestDTO request);

    ModelChatVO chat(ModelChatRequestDTO request);

    List<ModelChatStreamEventVO> streamChat(ModelChatRequestDTO request);
}
