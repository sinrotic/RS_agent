package com.sinrotic.rs.common.commerce;

public record TradeEvent(String eventId,long orderId,int version,String type,String accountId,String profileUserId,
                         String sessionId,String deliveryId,String itemId,int quantity,long amount,String provider,boolean mock,java.time.LocalDateTime occurredAt) {
    public void validate() {
        CommerceInput.id(eventId);CommerceInput.id(accountId);CommerceInput.id(itemId);CommerceInput.id(provider);
        if(profileUserId!=null) CommerceInput.id(profileUserId);
        if(occurredAt==null || orderId<=0 || quantity<1 || amount<=0 || !("PAID".equals(type) && version==1 || "REFUNDED".equals(type) && version==2)
                || mock!=provider.equalsIgnoreCase("mock")) throw CommerceInput.bad("交易事件不合法");
    }
}
