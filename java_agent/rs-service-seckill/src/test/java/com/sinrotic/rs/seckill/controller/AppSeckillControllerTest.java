package com.sinrotic.rs.seckill.controller;

import com.sinrotic.rs.seckill.domain.dto.SeckillSubmitRequestDTO;
import com.sinrotic.rs.seckill.domain.vo.SeckillSubmitVO;
import com.sinrotic.rs.seckill.service.SeckillService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AppSeckillControllerTest {

    @Test
    void submitUsesPathActivityIdInsteadOfBodyActivityId() {
        SeckillService seckillService = mock(SeckillService.class);
        AppSeckillController controller = new AppSeckillController(seckillService);
        SeckillSubmitRequestDTO body = new SeckillSubmitRequestDTO(
                "req-1",
                100L,
                "body-act",
                "item-1",
                "sku-1",
                1
        );
        when(seckillService.submit(org.mockito.ArgumentMatchers.any()))
                .thenReturn(new SeckillSubmitVO("req-1", "PROCESSING"));

        SeckillSubmitVO response = controller.submit("path-act", body);

        assertEquals("PROCESSING", response.status());
        ArgumentCaptor<SeckillSubmitRequestDTO> captor = ArgumentCaptor.forClass(SeckillSubmitRequestDTO.class);
        verify(seckillService).submit(captor.capture());
        assertEquals("path-act", captor.getValue().activityId());
    }

    @Test
    void submitPassesNullBodyToServiceValidation() {
        SeckillService seckillService = mock(SeckillService.class);
        AppSeckillController controller = new AppSeckillController(seckillService);
        when(seckillService.submit(isNull())).thenThrow(new IllegalArgumentException("request is required"));

        IllegalArgumentException thrown = assertThrows(
                IllegalArgumentException.class,
                () -> controller.submit("path-act", null)
        );

        assertEquals("request is required", thrown.getMessage());
        verify(seckillService).submit(null);
    }
}
