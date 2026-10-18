package com.sinrotic.rs.order.checkout;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
@Component
public class RefundPaymentClient {
    public record Result(String refundId,String status,boolean mock,boolean moneyMoved) {}
    public record Request(String refundId,long orderId,long amount,String scenario,boolean retryFailed) {}
    private final RestClient client;private final String token;
    public RefundPaymentClient(RestClient.Builder builder,@Value("${rs.payment.base-url:http://localhost:8093}") String url,
            @Value("${rs.commerce.service-token:}") String token) {
        this.token=token;var factory=new org.springframework.http.client.SimpleClientHttpRequestFactory();factory.setConnectTimeout(2000);factory.setReadTimeout(3000);
        client=builder.baseUrl(url).requestFactory(factory).build();
    }
    public Result refund(String id,long orderId,long amount,String scenario,boolean retryFailed) {
        var result=client.post().uri("/internal/payment/refunds").header("Authorization","Bearer "+token)
                .body(new Request(id,orderId,amount,scenario,retryFailed)).retrieve().body(Result.class);
        if(result==null || !id.equals(result.refundId())) throw new IllegalStateException("退款结果未确认");return result;
    }
}
