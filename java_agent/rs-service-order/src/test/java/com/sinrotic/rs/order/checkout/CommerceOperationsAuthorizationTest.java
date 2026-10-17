package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.common.commerce.CommerceOperationsConfiguration;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.mockito.Mockito.*;

class CommerceOperationsAuthorizationTest {
    String reader="r".repeat(32),writer="w".repeat(32);
    @Test void unauthenticatedAndReadOnlyCallsCannotModifyTasksAndAuditActorComesFromCredential() throws Exception {
        var service=mock(CheckoutService.class);
        var mvc=MockMvcBuilders.standaloneSetup(new InternalCheckoutController(service))
                .addFilters(new CommerceOperationsConfiguration.OperationsFilter(reader,writer,"authenticated-operator")).build();
        mvc.perform(get("/internal/checkout/tasks/summary")).andExpect(status().isUnauthorized());
        mvc.perform(get("/internal/checkout/tasks/summary").header("Authorization","Bearer "+reader)).andExpect(status().isOk());
        mvc.perform(post("/internal/checkout/tasks/10/retry").header("Authorization","Bearer "+reader)
                .contentType("application/json").content("{\"operatorId\":\"forged\",\"reason\":\"故障已排除\"}")).andExpect(status().isForbidden());
        mvc.perform(post("/internal/checkout/tasks/10/retry").header("Authorization","Bearer "+writer)
                .contentType("application/json").content("{\"operatorId\":\"forged\",\"reason\":\"故障已排除\"}")).andExpect(status().isOk());
        verify(service).retryTask(10,new CheckoutService.OperatorAction("authenticated-operator","故障已排除"));
    }
    @Test void unsetCredentialsFailClosedButBusinessReconciliationRouteRemainsAvailable() throws Exception {
        var mvc=MockMvcBuilders.standaloneSetup(new InternalCheckoutController(mock(CheckoutService.class)))
                .addFilters(new CommerceOperationsConfiguration.OperationsFilter("","","operator")).build();
        mvc.perform(get("/internal/checkout/tasks/summary").header("Authorization","Bearer guessed")).andExpect(status().isUnauthorized());
        mvc.perform(get("/internal/checkout/requests/event").param("accountId","account")).andExpect(status().isOk());
    }
}
