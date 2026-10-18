package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.order.client.InventoryClient;
import com.sinrotic.rs.common.commerce.WorkerLeaseStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.dao.DuplicateKeyException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Statement;
import java.time.Clock;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

@Service
public class CheckoutService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final InventoryClient inventory;
    private final PromotionClient promotion;
    private final Clock clock;
    private final WorkerLeaseStore leases;
    private final int maxAttempts;
    private final int batchSize;
    private final java.util.concurrent.ExecutorService workers;
    private final java.util.concurrent.locks.ReentrantLock pendingLock=new java.util.concurrent.locks.ReentrantLock();
    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(CheckoutService.class);

    public record CreateRequest(String requestId, String itemId, String skuId, Integer quantity,
                                String couponId, String sessionId, String recommendRequestId) {}
    public record Offer(String skuId, String itemId, String itemTitle, long unitPrice) {}
    public record OrderView(long orderId, String status, String phase, String itemId, String skuId, String itemTitle,
                            int quantity, long originalAmount, long discountAmount, long totalAmount, String couponId,
                            LocalDateTime expiresAt, String failureReason) {}
    public record TaskView(long orderId,String status,String phase,int attempts,String lastError,
                           LocalDateTime createdAt,LocalDateTime nextAttemptAt) {}
    public record OperatorAction(String operatorId,String reason) {}
    private record Work(long orderId, String accountId, String couponId, String itemId, String skuId,
                        int quantity, long originalAmount, String phase, String status, LocalDateTime expiresAt,String stockPoolId,String claimToken) {}
    private record TransitionState(String status,LocalDateTime expiresAt,long totalAmount,String couponId) {}

    @Autowired
    public CheckoutService(JdbcTemplate jdbc, PlatformTransactionManager manager, InventoryClient inventory, PromotionClient promotion,
            @org.springframework.beans.factory.annotation.Value("${rs.checkout.max-attempts:20}") int maxAttempts,
            @org.springframework.beans.factory.annotation.Value("${rs.checkout.worker.batch-size:100}") int batchSize,
            @org.springframework.beans.factory.annotation.Value("${rs.checkout.worker.concurrency:4}") int concurrency) {
        this(jdbc, manager, inventory, promotion, Clock.systemUTC(),maxAttempts,batchSize,concurrency);
    }
    public CheckoutService(JdbcTemplate jdbc, PlatformTransactionManager manager, InventoryClient inventory, PromotionClient promotion, Clock clock) {
        this(jdbc,manager,inventory,promotion,clock,20);
    }
    public CheckoutService(JdbcTemplate jdbc, PlatformTransactionManager manager, InventoryClient inventory, PromotionClient promotion, Clock clock,int maxAttempts) {
        this(jdbc,manager,inventory,promotion,clock,maxAttempts,100,4);
    }
    public CheckoutService(JdbcTemplate jdbc, PlatformTransactionManager manager, InventoryClient inventory, PromotionClient promotion,
            Clock clock,int maxAttempts,int batchSize,int concurrency) {
        this.jdbc = jdbc; this.tx = new TransactionTemplate(manager);
        this.inventory = inventory; this.promotion = promotion; this.clock = clock;
        this.leases=new WorkerLeaseStore(jdbc);
        if(maxAttempts<1 || maxAttempts>1000) throw new IllegalArgumentException("重试上限须为 1 到 1000");
        this.maxAttempts=maxAttempts;
        if(batchSize<1 || batchSize>500 || concurrency<1 || concurrency>16) throw new IllegalArgumentException("订单批大小须为 1 到 500，并发须为 1 到 16");
        this.batchSize=batchSize;
        workers=new java.util.concurrent.ThreadPoolExecutor(concurrency,concurrency,0L,java.util.concurrent.TimeUnit.MILLISECONDS,
                new java.util.concurrent.ArrayBlockingQueue<>(batchSize),r -> { var thread=new Thread(r,"checkout-worker");thread.setDaemon(true);return thread; });
    }
    @jakarta.annotation.PreDestroy
    public void close() { workers.shutdownNow(); }

    public List<Offer> offers(String itemId) {
        text(itemId);
        return jdbc.query("SELECT * FROM checkout_offer WHERE item_id = ? AND active = TRUE ORDER BY sku_id LIMIT 100",
                (r,n) -> new Offer(r.getString("sku_id"),r.getString("item_id"),r.getString("item_title"),r.getLong("unit_price")), itemId);
    }

    public OrderView create(String accountId, String profileUserId, CreateRequest request) {
        return createInternal(accountId,profileUserId,request,null,null);
    }

    public OrderView createAccepted(String accountId, CreateRequest request, Offer snapshot) {
        return createAccepted(accountId,request,snapshot,null);
    }
    public OrderView createAccepted(String accountId, CreateRequest request, Offer snapshot,String stockPoolId) {
        optional(stockPoolId);
        if (snapshot == null || snapshot.unitPrice() <= 0 || snapshot.itemTitle() == null
                || snapshot.itemTitle().length() > 255 || !snapshot.itemId().equals(request.itemId())
                || !snapshot.skuId().equals(request.skuId())) throw bad("秒杀商品快照不合法");
        return createInternal(accountId,null,request,snapshot,stockPoolId);
    }

    private OrderView createInternal(String accountId, String profileUserId, CreateRequest request, Offer snapshot,String stockPoolId) {
        text(accountId);
        if (request == null) throw bad("订单不能为空");
        text(request.requestId()); text(request.itemId()); text(request.skuId());
        optional(request.couponId()); optional(request.sessionId()); optional(request.recommendRequestId()); optional(profileUserId);
        if (request.quantity() == null || request.quantity() < 1 || request.quantity() > 99) throw bad("购买数量须为 1 到 99");
        String fingerprint = fingerprint(request,stockPoolId);
        var existing = existing(accountId, request.requestId(), fingerprint);
        if (existing != null) return existing;
        Offer offer = snapshot != null ? snapshot : offers(request.itemId()).stream().filter(o -> o.skuId().equals(request.skuId())).findFirst()
                .orElseThrow(() -> conflict("此 SKU 暂未开放交易"));
        long amount;
        try { amount = Math.multiplyExact(offer.unitPrice(), request.quantity().longValue()); }
        catch (ArithmeticException ex) { throw bad("订单金额超限"); }
        try {
            long id = Objects.requireNonNull(tx.execute(status -> {
                GeneratedKeyHolder key = new GeneratedKeyHolder();
                jdbc.update(connection -> {
                    var statement = connection.prepareStatement("INSERT INTO checkout_id(marker) VALUES (1)", Statement.RETURN_GENERATED_KEYS);
                    return statement;
                }, key);
                long orderId = Objects.requireNonNull(key.getKey()).longValue();
                jdbc.update("""
                        INSERT INTO orders(order_id,request_id,account_id,profile_user_id,session_id,recommend_request_id,status,total_amount)
                        VALUES (?,?,?,?,?,?,'CREATING',?)
                        """, orderId, UUID.randomUUID().toString(), accountId, profileUserId,
                        request.sessionId(),request.recommendRequestId(),amount);
                jdbc.update("""
                        INSERT INTO order_items(order_id,item_id,sku_id,item_title,quantity,unit_price,total_amount)
                        VALUES (?,?,?,?,?,?,?)
                        """,orderId,offer.itemId(),offer.skuId(),offer.itemTitle(),request.quantity(),offer.unitPrice(),amount);
                jdbc.update("""
                        INSERT INTO checkout_workflow(order_id,account_id,client_request_id,fingerprint,coupon_id,
                        original_amount,phase,next_attempt_at,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,orderId,accountId,request.requestId(),fingerprint,request.couponId(),amount,
                        request.couponId() == null ? "LOCK_STOCK" : "LOCK_COUPON",now(),now(),now().plusMinutes(15));
                if(stockPoolId!=null) jdbc.update("INSERT INTO checkout_stock_scope(order_id,activity_id) VALUES (?,?)",orderId,stockPoolId);
                return orderId;
            }));
            return get(accountId, id);
        } catch (DuplicateKeyException ex) {
            var duplicate = existing(accountId, request.requestId(), fingerprint);
            if (duplicate == null) throw ex;
            return duplicate;
        }
    }

    public boolean owns(long orderId) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM checkout_workflow WHERE order_id = ?",Integer.class,orderId) == 1;
    }

    public OrderView byRequest(String accountId, String requestId) {
        var rows = views("w.account_id = ? AND w.client_request_id = ?",accountId,requestId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"订单尚未创建");
        return rows.getFirst();
    }

    public List<OrderView> list(String accountId) {
        text(accountId);
        return views("w.account_id = ? ORDER BY w.created_at DESC, w.order_id DESC LIMIT 50",accountId);
    }
    public com.sinrotic.rs.common.commerce.CommerceInput.Page<OrderView> page(String accountId,Long beforeId,String itemId,int limit) {
        text(accountId);com.sinrotic.rs.common.commerce.CommerceInput.limit(limit);optional(itemId);
        if(beforeId!=null && beforeId<=0) throw bad("订单游标不合法");
        var args=new java.util.ArrayList<Object>();args.add(accountId);args.add(beforeId==null ? Long.MAX_VALUE : beforeId);
        String filter="w.account_id=? AND w.order_id<?";
        if(itemId!=null) {filter+=" AND i.item_id=?";args.add(itemId);}
        args.add(limit+1);var found=views(filter+" ORDER BY w.order_id DESC LIMIT ?",args.toArray());
        boolean more=found.size()>limit;var items=more ? found.subList(0,limit) : found;
        return new com.sinrotic.rs.common.commerce.CommerceInput.Page<>(items,more ? Long.toString(items.getLast().orderId()) : null);
    }
    public OrderView get(String accountId, long orderId) {
        text(accountId);
        var rows = views("w.account_id = ? AND w.order_id = ?",accountId,orderId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"订单不存在");
        return rows.getFirst();
    }
    public OrderView cancel(String accountId, long orderId) {
        get(accountId,orderId);
        transition(orderId,"CANCELED",false);
        return get(accountId,orderId);
    }
    public OrderView payableOrder(String accountId, long orderId) {
        var order = get(accountId, orderId);
        if (!"WAITING_PAYMENT".equals(order.status()) || !"READY".equals(order.phase())
                || order.expiresAt() == null || !now().isBefore(order.expiresAt())) {
            throw conflict("订单当前不可支付");
        }
        return order;
    }
    public void paid(long orderId) { transition(orderId,"PAID",true); }
    public void paidFromProvider(long orderId,Long amount,String provider,String transactionId) {
        text(provider);
        if (transactionId == null || transactionId.isBlank() || transactionId.length() > 128) throw bad("支付流水不合法");
        if (amount == null || amount <= 0) throw conflict("支付金额与订单应付金额不符");
        tx.executeWithoutResult(s -> {
            // 支付通知可能在响应丢失后晚于退款重放。先核对不可变原支付，不能把退款状态退回 PAID。
            if(jdbc.queryForList("SELECT o.order_id FROM checkout_workflow w JOIN orders o ON o.order_id=w.order_id WHERE w.order_id=? FOR UPDATE",orderId).isEmpty())
                throw new ResponseStatusException(HttpStatus.NOT_FOUND,"订单不存在");
            var previous=jdbc.queryForList("SELECT * FROM checkout_payment_fact WHERE order_id=?",orderId);
            if(!previous.isEmpty()) {
                if(!provider.equals(previous.getFirst().get("provider")) || !transactionId.equals(previous.getFirst().get("transaction_id"))
                        || amount!=((Number)previous.getFirst().get("amount")).longValue()) throw conflict("支付事实与原流水不一致");
                return;
            }
            transition(orderId,"PAID",true,amount);
            jdbc.update("INSERT INTO checkout_payment_fact(order_id,provider,transaction_id,amount,mock,created_at) VALUES (?,?,?,?,?,?)",orderId,provider,transactionId,amount,"mock".equalsIgnoreCase(provider),now());
            OrderTradeEvents.append(jdbc,orderId,"PAID",now());
        });
    }
    public void closeTimeout(long orderId) {
        var expiry = jdbc.queryForList("SELECT expires_at FROM checkout_workflow WHERE order_id = ? AND expires_at <= ?",orderId,now());
        if (expiry.isEmpty()) return;
        transition(orderId,"TIMEOUT_CLOSED",false);
    }

    private void transition(long orderId, String target, boolean paid) {
        transition(orderId,target,paid,null);
    }
    private void transition(long orderId, String target, boolean paid, Long paidAmount) {
        tx.executeWithoutResult(transaction -> {
            var rows = jdbc.query("""
                    SELECT w.phase,o.status,w.expires_at,o.total_amount,w.coupon_id FROM checkout_workflow w JOIN orders o ON o.order_id = w.order_id
                    WHERE w.order_id = ? FOR UPDATE
                    """,(r,n) -> new TransitionState(r.getString("status"),r.getObject("expires_at",LocalDateTime.class),r.getLong("total_amount"),r.getString("coupon_id")),orderId);
            if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"订单不存在");
            if (paidAmount != null && paidAmount != rows.getFirst().totalAmount()) throw conflict("支付金额与订单应付金额不符");
            String state = rows.getFirst().status();
            if (target.equals(state)) return;
            boolean creating = "CREATING".equals(state);
            if (!"WAITING_PAYMENT".equals(state) && !(creating && !paid)) throw conflict("订单当前状态不允许此操作");
            LocalDateTime expiry = rows.getFirst().expiresAt();
            if (paid && !now().isBefore(expiry)) throw conflict("订单已超时，支付结果需进入人工退款核对");
            jdbc.update("UPDATE orders SET status = ?, updated_at = ?, paid_at = ?, closed_at = ? WHERE order_id = ?",
                    target,now(),paid ? now() : null,paid ? null : now(),orderId);
            // 与订单状态同事务提交的持久待办；远程调用失败不会丢失后续工作。
            String cleanupPhase = creating
                    ? rows.getFirst().couponId() == null ? "CANCEL_STOCK" : "CANCEL_COUPON"
                    : paid ? "CONFIRM_STOCK" : "RELEASE_STOCK";
            jdbc.update("UPDATE checkout_workflow SET phase = ?, next_attempt_at = ?, attempts = 0, last_error = NULL WHERE order_id = ?",
                    cleanupPhase,now(),orderId);
        });
    }

    public void processPending() {
        if(!pendingLock.tryLock()) return;
        try {
        var expired = jdbc.queryForList("""
                SELECT w.order_id FROM checkout_workflow w JOIN orders o ON o.order_id=w.order_id
                WHERE o.status IN ('CREATING','WAITING_PAYMENT') AND w.expires_at <= ? ORDER BY w.expires_at LIMIT ?
                """,Long.class,now(),batchSize);
        for (long id : expired) {
            try { closeTimeout(id); } catch (ResponseStatusException ignored) { /* 支付/取消可能已抢先完成。 */ }
        }
        var ids = jdbc.queryForList("""
                SELECT order_id FROM checkout_workflow WHERE phase NOT IN ('READY','DONE','FAILED')
                AND phase NOT LIKE 'REVIEW_%'
                AND next_attempt_at <= ? ORDER BY next_attempt_at,order_id LIMIT ?
                """,Long.class,now(),batchSize);
        var tasks=new java.util.ArrayList<java.util.concurrent.Callable<Void>>();
        for(long id:ids) tasks.add(() -> { process(id);return null; });
        try {
            for(var future:workers.invokeAll(tasks)) {
                try { future.get(); }
                catch(java.util.concurrent.ExecutionException failure) { log.warn("订单批次的单个任务失败，其他任务继续处理",failure.getCause()); }
            }
        } catch(InterruptedException interrupted) { Thread.currentThread().interrupt(); }
        } finally { pendingLock.unlock(); }
    }

    public void process(long orderId) {
        String token=leases.acquire("checkout",Long.toString(orderId));
        if(token==null) return;
        try {processClaimed(orderId,token);}
        finally {leases.release("checkout",Long.toString(orderId),token);}
    }
    private void processClaimed(long orderId,String token) {
        for (int step = 0; step < 4; step++) {
            if(!Boolean.TRUE.equals(tx.execute(s -> leases.owns("checkout",Long.toString(orderId),token)))) return;
            Work work = work(orderId,token);
            if (work == null || List.of("READY","DONE","FAILED").contains(work.phase()) || work.phase().startsWith("REVIEW_")) return;
            if ("CREATING".equals(work.status()) && !now().isBefore(work.expiresAt())) {
                closeTimeout(orderId);
                continue;
            }
            try {
                switch (work.phase()) {
                    case "CANCEL_COUPON" -> {
                        promotion.cancel(orderId,work.couponId(),work.accountId(),work.itemId(),work.originalAmount());
                        advance(work,"CANCEL_STOCK",null);
                    }
                    case "CANCEL_STOCK" -> {
                        stock(work,"CANCEL");
                        advance(work,"DONE",null);
                    }
                    case "LOCK_COUPON" -> {
                        long discount = promotion.lock(orderId,work.couponId(),work.accountId(),work.itemId(),work.originalAmount());
                        if (discount <= 0 || discount >= work.originalAmount()) throw new IllegalStateException("促销服务返回异常优惠金额");
                        tx.executeWithoutResult(s -> {
                            if(!owns(work)) return;
                            int updated = jdbc.update("""
                                    UPDATE checkout_workflow SET phase = 'LOCK_STOCK', discount_amount = ?, attempts = 0,
                                    next_attempt_at = ?, last_error = NULL WHERE order_id = ? AND phase = 'LOCK_COUPON'
                                    """,discount,now(),orderId);
                            if (updated == 1) jdbc.update("UPDATE orders SET total_amount = ? WHERE order_id = ?",work.originalAmount()-discount,orderId);
                        });
                    }
                    case "LOCK_STOCK" -> {
                        stock(work,"LOCK");
                        advance(work,"READY","WAITING_PAYMENT");
                    }
                    case "CONFIRM_STOCK" -> {
                        stock(work,"CONFIRM");
                        advance(work,work.couponId() == null ? "DONE" : "CONFIRM_COUPON",null);
                    }
                    case "RELEASE_STOCK" -> {
                        stock(work,"RELEASE");
                        advance(work,work.couponId() == null ? "DONE" : "RELEASE_COUPON",null);
                    }
                    case "CONFIRM_COUPON" -> {
                        promotion.confirm(orderId,work.couponId()); advance(work,"DONE",null);
                    }
                    case "RELEASE_COUPON" -> {
                        promotion.release(orderId,work.couponId()); advance(work,"DONE",null);
                    }
                    case "ABORT_COUPON" -> {
                        promotion.release(orderId,work.couponId()); advance(work,"FAILED","CREATION_FAILED");
                    }
                    default -> throw new IllegalStateException("未知订单处理阶段");
                }
            } catch (RuntimeException failure) {
                if (isDefinitiveRejection(failure) && ("LOCK_COUPON".equals(work.phase()) || "LOCK_STOCK".equals(work.phase()))) {
                    boolean releaseCoupon = "LOCK_STOCK".equals(work.phase()) && work.couponId() != null;
                    advance(work,releaseCoupon ? "ABORT_COUPON" : "FAILED",releaseCoupon ? null : "CREATION_FAILED");
                    jdbc.update("UPDATE checkout_workflow SET last_error = ? WHERE order_id = ? AND phase = ?",
                            "优惠券不可用或库存不足",orderId,releaseCoupon ? "ABORT_COUPON" : "FAILED");
                } else {
                    recordFailure(work,failure);
                    log.warn("订单 {} 的 {} 操作失败，已保存重试或待核对状态",orderId,work.phase(),failure);
                }
                return;
            }
        }
    }
    private void recordFailure(Work work,RuntimeException failure) {
        tx.executeWithoutResult(s -> {
            if(!owns(work)) return;
            var rows=jdbc.queryForList("SELECT phase,attempts FROM checkout_workflow WHERE order_id=? FOR UPDATE",work.orderId());
            if(rows.isEmpty() || !work.phase().equals(rows.getFirst().get("phase"))) return;
            int attempts=((Number)rows.getFirst().get("attempts")).intValue()+1;
            boolean definitive=failure instanceof HttpClientErrorException http && http.getStatusCode().is4xxClientError()
                    && http.getStatusCode().value()!=429 && http.getStatusCode().value()!=408;
            boolean review=definitive || attempts>=maxAttempts;
            long delay=Math.min(60L,5L << Math.min(4,attempts-1));
            String error=review ? "处理暂停，需核对后恢复；"+failure.getClass().getSimpleName()
                    : "服务暂不可用，正在重试";
            if(failure instanceof HttpClientErrorException http) error+="：HTTP "+http.getStatusCode().value();
            jdbc.update("UPDATE checkout_workflow SET phase=?,attempts=?,next_attempt_at=?,last_error=? WHERE order_id=?",
                    review ? "REVIEW_"+work.phase() : work.phase(),attempts,now().plusSeconds(delay),error,work.orderId());
        });
    }

    public List<TaskView> stalledTasks(int minimumAgeSeconds) {
        if(minimumAgeSeconds<0 || minimumAgeSeconds>2592000) throw bad("查询年龄范围不合法");
        return jdbc.query("""
                SELECT w.*,o.status FROM checkout_workflow w JOIN orders o ON o.order_id=w.order_id
                WHERE w.phase NOT IN ('READY','DONE','FAILED') AND (w.phase LIKE 'REVIEW_%' OR w.created_at<=?)
                ORDER BY w.created_at,w.order_id LIMIT 100
                """,(r,n)->new TaskView(r.getLong("order_id"),r.getString("status"),r.getString("phase"),
                r.getInt("attempts"),r.getString("last_error"),r.getObject("created_at",LocalDateTime.class),
                r.getObject("next_attempt_at",LocalDateTime.class)),now().minusSeconds(minimumAgeSeconds));
    }

    public java.util.Map<String,Long> taskSummary() {
        return jdbc.queryForObject("""
                SELECT COUNT(*) AS pending,COALESCE(SUM(CASE WHEN phase LIKE 'REVIEW_%' THEN 1 ELSE 0 END),0) AS review_count
                FROM checkout_workflow WHERE phase NOT IN ('READY','DONE','FAILED')
                """,(r,n)->java.util.Map.of("pending",r.getLong("pending"),"reviewRequired",r.getLong("review_count")));
    }

    public void retryTask(long orderId,OperatorAction action) {
        if(action==null) throw bad("操作人和原因不能为空");
        text(action.operatorId());
        if(action.reason()==null || action.reason().isBlank() || action.reason().length()>255) throw bad("恢复原因不合法");
        tx.executeWithoutResult(s -> {
            var rows=jdbc.queryForList("SELECT phase FROM checkout_workflow WHERE order_id=? FOR UPDATE",orderId);
            if(rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"订单任务不存在");
            String phase=(String)rows.getFirst().get("phase");
            if(!phase.startsWith("REVIEW_")) throw conflict("仅可恢复待核对的任务");
            jdbc.update("UPDATE checkout_workflow SET phase=?,attempts=0,next_attempt_at=?,last_error=NULL WHERE order_id=?",
                    phase.substring(7),now(),orderId);
            jdbc.update("""
                    INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at)
                    VALUES ('checkout',?,?,'RETRY',?,?)
                    """,Long.toString(orderId),action.operatorId(),action.reason(),now());
        });
    }
    private void advance(Work work, String phase, String orderStatus) {
        tx.executeWithoutResult(s -> {
            if(!owns(work)) return;
            int changed = jdbc.update("""
                    UPDATE checkout_workflow SET phase = ?, attempts = 0, next_attempt_at = ?, last_error = NULL
                    WHERE order_id = ? AND phase = ?
                    """,phase,now(),work.orderId(),work.phase());
            if (changed == 1 && orderStatus != null)
                jdbc.update("UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",orderStatus,now(),work.orderId());
        });
    }
    private boolean owns(Work work) {return leases.owns("checkout",Long.toString(work.orderId()),work.claimToken());}
    private void stock(Work work,String action) {
        if(work.stockPoolId()!=null) {inventory.activity(action,work.stockPoolId(),work.orderId(),work.skuId(),work.quantity());return;}
        String key=stockKey(work.orderId(),action.toLowerCase(java.util.Locale.ROOT));
        switch(action) {
            case "LOCK" -> inventory.lock(key,work.orderId(),work.skuId(),work.quantity());
            case "CONFIRM" -> inventory.confirm(key,work.orderId(),work.skuId(),work.quantity());
            case "RELEASE" -> inventory.release(key,work.orderId(),work.skuId(),work.quantity());
            case "CANCEL" -> inventory.cancel(key,work.orderId(),work.skuId(),work.quantity());
            default -> throw new IllegalArgumentException("未知库存操作");
        }
    }
    private Work work(long orderId,String token) {
        var rows = jdbc.query("""
                SELECT w.*,i.item_id,i.sku_id,i.quantity,o.status,p.activity_id FROM checkout_workflow w
                JOIN order_items i ON i.order_id = w.order_id JOIN orders o ON o.order_id = w.order_id
                LEFT JOIN checkout_stock_scope p ON p.order_id=w.order_id WHERE w.order_id = ?
                """,(r,n) -> new Work(r.getLong("order_id"),r.getString("account_id"),r.getString("coupon_id"),
                r.getString("item_id"),r.getString("sku_id"),r.getInt("quantity"),r.getLong("original_amount"),r.getString("phase"),
                r.getString("status"),r.getObject("expires_at",LocalDateTime.class),r.getString("activity_id"),token),orderId);
        return rows.isEmpty() ? null : rows.getFirst();
    }
    private OrderView existing(String accountId, String requestId, String fingerprint) {
        var rows = jdbc.queryForList("SELECT order_id,fingerprint FROM checkout_workflow WHERE account_id = ? AND client_request_id = ?",accountId,requestId);
        if (rows.isEmpty()) return null;
        if (!fingerprint.equals(rows.getFirst().get("fingerprint"))) throw conflict("相同幂等键不能用于不同订单参数");
        return get(accountId,((Number)rows.getFirst().get("order_id")).longValue());
    }
    private List<OrderView> views(String where, Object... args) {
        return jdbc.query("""
                SELECT w.*,o.status,o.total_amount,i.item_id,i.sku_id,i.item_title,i.quantity
                FROM checkout_workflow w JOIN orders o ON o.order_id = w.order_id
                JOIN order_items i ON i.order_id = w.order_id WHERE
                """ + where,(r,n) -> new OrderView(r.getLong("order_id"),r.getString("status"),r.getString("phase"),
                r.getString("item_id"),r.getString("sku_id"),r.getString("item_title"),r.getInt("quantity"),r.getLong("original_amount"),
                r.getLong("discount_amount"),r.getLong("total_amount"),r.getString("coupon_id"),
                r.getObject("expires_at",LocalDateTime.class),r.getString("last_error")),args);
    }
    private boolean isDefinitiveRejection(RuntimeException ex) {
        return ex instanceof HttpClientErrorException http && (http.getStatusCode().value() == 409 || http.getStatusCode().value() == 404);
    }
    private static String stockKey(long orderId,String action) { return "checkout:" + orderId + ":" + action; }
    private LocalDateTime now() { return LocalDateTime.now(clock); }
    private static String fingerprint(CreateRequest r,String stockPoolId) {
        try {
            // 长度前缀避免用户输入分隔符导致参数串碰撞。
            StringBuilder input = new StringBuilder();
            for (String field : new String[]{r.itemId(),r.skuId(),r.quantity().toString(),r.couponId(),r.sessionId(),r.recommendRequestId()})
                input.append(field == null ? -1 : field.length()).append(':').append(field == null ? "" : field);
            if(stockPoolId!=null) input.append("pool:").append(stockPoolId.length()).append(':').append(stockPoolId);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(input.toString().getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private static void optional(String value) { if (value != null) text(value); }
    private static void text(String value) {
        if (value == null || value.isBlank() || value.length() > 64 || !value.equals(value.trim())) throw bad("标识为空或格式不合法");
    }
    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST,message); }
    private static ResponseStatusException conflict(String message) { return new ResponseStatusException(HttpStatus.CONFLICT,message); }
}
