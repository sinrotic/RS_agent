package com.sinrotic.rs.seckill.service;

import com.sinrotic.rs.seckill.domain.dto.SeckillSubmitRequestDTO;
import com.sinrotic.rs.seckill.domain.vo.SeckillSubmitVO;
import com.sinrotic.rs.common.commerce.WorkerLeaseStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.json.JsonMapper;

import java.time.Clock;
import java.time.LocalDateTime;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.ArrayList;

@Service
public class SeckillService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final StringRedisTemplate redis;
    private final KafkaTemplate<String,String> kafka;
    private final JsonMapper mapper;
    private final SeckillOrderClient orders;
    private final SeckillInventoryClient inventory;
    private final WorkerLeaseStore leases;
    private final Clock clock;
    private final int admissionLimit;
    private final int maxRedrives;
    private final int batchSize;
    private final ExecutorService publishers;
    private final ExecutorService reconcilers;
    private final java.util.concurrent.locks.ReentrantLock dispatchLock=new java.util.concurrent.locks.ReentrantLock();
    private final java.util.concurrent.locks.ReentrantLock reconcileLock=new java.util.concurrent.locks.ReentrantLock();
    private static final List<String> TERMINAL = List.of("PAID","FAILED","CANCELED","TIMEOUT_CLOSED","REFUNDED");
    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(SeckillService.class);
    private static final DefaultRedisScript<Long> ADMISSION = new DefaultRedisScript<>("""
            local count = tonumber(redis.call('GET',KEYS[1]) or '0')
            if count >= tonumber(ARGV[1]) then return 0 end
            local value = redis.call('INCR',KEYS[1])
            if value == 1 then redis.call('PEXPIRE',KEYS[1],1000) end
            return 1
            """,Long.class);
    public record Activity(String activityId,String itemId,String skuId,int totalQuantity,
                           LocalDateTime startsAt,LocalDateTime endsAt) {}
    public record Accepted(String eventId,String requestId,String accountId,String activityId,
                           String itemId,String skuId,int quantity,String itemTitle,long unitPrice,String stockPoolId) {}
    public record ActivityView(String activityId,String itemId,String skuId,String itemTitle,long unitPrice,
                               int totalQuantity,int remainingQuantity,Instant startsAt,Instant endsAt,
                               Instant serverTime,String status,SeckillSubmitVO participation,String inventoryMode) {}
    public record TaskView(String eventId,String requestId,String activityId,String status,Long orderId,
                           int attempts,String lastError,Instant createdAt,Instant nextAttemptAt) {}
    public record OperatorAction(String operatorId,String reason) {}

    @Autowired
    public SeckillService(JdbcTemplate jdbc,PlatformTransactionManager manager,StringRedisTemplate redis,
            KafkaTemplate<String,String> kafka,JsonMapper mapper,SeckillOrderClient orders,SeckillInventoryClient inventory,
            @Value("${rs.seckill.admissions-per-second:200}") int admissionLimit,
            @Value("${rs.seckill.max-redrives:10}") int maxRedrives,
            @Value("${rs.seckill.worker.batch-size:100}") int batchSize,
            @Value("${rs.seckill.worker.publish-concurrency:4}") int publishConcurrency,
            @Value("${rs.seckill.worker.reconcile-concurrency:4}") int reconcileConcurrency) {
        this(jdbc,manager,redis,kafka,mapper,orders,inventory,Clock.systemUTC(),admissionLimit,maxRedrives,batchSize,publishConcurrency,reconcileConcurrency);
    }
    public SeckillService(JdbcTemplate jdbc,PlatformTransactionManager manager,StringRedisTemplate redis,
            KafkaTemplate<String,String> kafka,JsonMapper mapper,SeckillOrderClient orders,SeckillInventoryClient inventory,Clock clock,int limit) {
        this(jdbc,manager,redis,kafka,mapper,orders,inventory,clock,limit,10);
    }
    public SeckillService(JdbcTemplate jdbc,PlatformTransactionManager manager,StringRedisTemplate redis,
            KafkaTemplate<String,String> kafka,JsonMapper mapper,SeckillOrderClient orders,SeckillInventoryClient inventory,Clock clock,int limit,int maxRedrives) {
        this(jdbc,manager,redis,kafka,mapper,orders,inventory,clock,limit,maxRedrives,100,4,4);
    }
    public SeckillService(JdbcTemplate jdbc,PlatformTransactionManager manager,StringRedisTemplate redis,
            KafkaTemplate<String,String> kafka,JsonMapper mapper,SeckillOrderClient orders,SeckillInventoryClient inventory,Clock clock,int limit,int maxRedrives,
            int batchSize,int publishConcurrency,int reconcileConcurrency) {
        this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);this.redis=redis;this.kafka=kafka;
        this.mapper=mapper;this.orders=orders;this.inventory=inventory;this.leases=new WorkerLeaseStore(jdbc);this.clock=clock;this.admissionLimit=Math.max(1,limit);
        this.maxRedrives=Math.max(1,maxRedrives);
        if(batchSize<1 || batchSize>500) throw new IllegalArgumentException("批大小须为 1 到 500");
        this.batchSize=batchSize;
        this.publishers=pool("seckill-publish",publishConcurrency,batchSize);
        this.reconcilers=pool("seckill-reconcile",reconcileConcurrency,batchSize);
    }
    private static ExecutorService pool(String name,int concurrency,int capacity) {
        if(concurrency<1 || concurrency>16) throw new IllegalArgumentException("并发数须为 1 到 16");
        return new ThreadPoolExecutor(concurrency,concurrency,0L,TimeUnit.MILLISECONDS,new ArrayBlockingQueue<>(capacity),r -> {
            Thread thread=new Thread(r,name);thread.setDaemon(true);return thread;
        });
    }
    @jakarta.annotation.PreDestroy
    public void close() { publishers.shutdownNow();reconcilers.shutdownNow(); }
    private void runBatch(ExecutorService executor,List<Map<String,Object>> rows,java.util.function.Consumer<Map<String,Object>> action) {
        var tasks=new ArrayList<Callable<Void>>();
        for(var row:rows) tasks.add(() -> { action.accept(row);return null; });
        try {
            for(var future:executor.invokeAll(tasks)) {
                try { future.get(); }
                catch(ExecutionException failure) { log.warn("秒杀批次的单个任务失败，其他任务继续处理",failure.getCause()); }
            }
        } catch(InterruptedException interrupted) { Thread.currentThread().interrupt(); }
    }

    public List<ActivityView> activities(String accountId,String itemId) {
        text(accountId);text(itemId);
        return activityViews("a.item_id=? AND a.ends_at>? ORDER BY a.starts_at,a.activity_id LIMIT 100",accountId,itemId,now().minusDays(1));
    }
    public com.sinrotic.rs.common.commerce.CommerceInput.Page<Map<String,Object>> managementActivities(String afterId,int limit) {
        com.sinrotic.rs.common.commerce.CommerceInput.limit(limit);if(afterId!=null) text(afterId);
        var rows=jdbc.queryForList("SELECT a.*,p.status AS allocation_status,p.last_error FROM seckill_activity_v1 a LEFT JOIN seckill_activity_allocation p ON p.activity_id=a.activity_id WHERE a.activity_id>? ORDER BY a.activity_id LIMIT ?",afterId==null ? "" : afterId,limit+1);
        boolean more=rows.size()>limit;var items=more ? rows.subList(0,limit) : rows;return new com.sinrotic.rs.common.commerce.CommerceInput.Page<>(items,more ? (String)items.getLast().get("activity_id") : null);
    }
    public ActivityView activity(String accountId,String activityId) {
        text(accountId);text(activityId);
        var rows=activityViews("a.activity_id=?",accountId,activityId);
        if(rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"活动不存在");
        return rows.getFirst();
    }
    private List<ActivityView> activityViews(String condition,String accountId,Object... parameters) {
        Object[] arguments=new Object[parameters.length+1];arguments[0]=accountId;
        System.arraycopy(parameters,0,arguments,1,parameters.length);
        return jdbc.query("""
                SELECT a.*,r.request_id,r.status AS request_status,r.order_id,p.status AS allocation_status
                FROM seckill_activity_v1 a LEFT JOIN seckill_request_v1 r
                ON r.activity_id=a.activity_id AND r.account_id=?
                LEFT JOIN seckill_activity_allocation p ON p.activity_id=a.activity_id WHERE
                """+condition,(r,n) -> {
            var starts=r.getObject("starts_at",LocalDateTime.class);var ends=r.getObject("ends_at",LocalDateTime.class);
            String status=now().isBefore(starts) ? "NOT_STARTED" : !now().isBefore(ends) ? "ENDED"
                    : r.getInt("remaining_quantity")==0 ? "SOLD_OUT" : "ACTIVE";
            if(now().isBefore(ends) && r.getString("allocation_status")!=null && !"READY".equals(r.getString("allocation_status")))
                status="REVIEW".equals(r.getString("allocation_status")) ? "UNAVAILABLE" : "PREPARING";
            var participation=r.getString("request_id")==null ? null : new SeckillSubmitVO(r.getString("request_id"),
                    r.getString("request_status"),r.getObject("order_id",Long.class));
            return new ActivityView(r.getString("activity_id"),r.getString("item_id"),r.getString("sku_id"),
                    r.getString("item_title"),r.getLong("unit_price"),r.getInt("total_quantity"),r.getInt("remaining_quantity"),
                    starts.toInstant(ZoneOffset.UTC),ends.toInstant(ZoneOffset.UTC),clock.instant(),status,participation,
                    r.getString("allocation_status")==null ? "SHARED_LEGACY" : "ALLOCATED");
        },arguments);
    }

    public void createActivity(Activity activity) {
        if(activity == null) throw bad("活动不能为空");
        text(activity.activityId());text(activity.itemId());text(activity.skuId());
        if(activity.totalQuantity() <= 0 || activity.startsAt() == null || activity.endsAt() == null
                || !activity.startsAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS).isBefore(activity.endsAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS)))
            throw bad("活动额度或时间不合法");
        var existing=jdbc.queryForList("SELECT * FROM seckill_activity_v1 WHERE activity_id=?",activity.activityId());
        if(!existing.isEmpty()) {validateActivityReplay(existing.getFirst(),activity);provision(activity.activityId());return;}
        SeckillOrderClient.Offer offer=orders.offer(activity.itemId(),activity.skuId());
        if(offer == null) throw bad("活动 SKU 尚未开放交易");
        // 快照与待划拨记录同事务持久化；远程响应未知时后台沿原活动重试。
        try { tx.executeWithoutResult(s -> {
        jdbc.update("""
                INSERT INTO seckill_activity_v1(activity_id,item_id,sku_id,item_title,unit_price,total_quantity,remaining_quantity,starts_at,ends_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,activity.activityId(),activity.itemId(),activity.skuId(),offer.itemTitle(),offer.unitPrice(),
                activity.totalQuantity(),activity.totalQuantity(),activity.startsAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS),activity.endsAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS));
        jdbc.update("INSERT INTO seckill_activity_allocation(activity_id,next_attempt_at,phase_started_at) VALUES (?,?,?)",activity.activityId(),now(),now());
        }); } catch(DuplicateKeyException duplicate) {
            var row=jdbc.queryForMap("SELECT * FROM seckill_activity_v1 WHERE activity_id=?",activity.activityId());
            validateActivityReplay(row,activity);
        }
        provision(activity.activityId());
    }
    private static void validateActivityReplay(Map<String,Object> row,Activity activity) {
        if(!activity.itemId().equals(row.get("item_id")) || !activity.skuId().equals(row.get("sku_id"))
                || activity.totalQuantity()!=((Number)row.get("total_quantity")).intValue()
                || !activity.startsAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS).equals(date(row.get("starts_at")))
                || !activity.endsAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS).equals(date(row.get("ends_at"))))
            throw new ResponseStatusException(HttpStatus.CONFLICT,"活动参数不能覆盖");
    }

    public void maintainAllocations() {
        var ids=jdbc.queryForList("""
                SELECT p.activity_id FROM seckill_activity_allocation p JOIN seckill_activity_v1 a ON a.activity_id=p.activity_id
                WHERE p.next_attempt_at<=? AND (p.status IN ('PENDING','CLOSING') OR (p.status='READY' AND a.ends_at<=?))
                ORDER BY p.next_attempt_at LIMIT ?
                """,String.class,now(),now(),batchSize);
        for(String id:ids) provision(id);
    }
    private void provision(String id) {
        String token=leases.acquire("allocation",id);
        if(token==null) return;
        try {
            var rows=jdbc.queryForList("SELECT a.*,p.status AS allocation_status FROM seckill_activity_v1 a JOIN seckill_activity_allocation p ON p.activity_id=a.activity_id WHERE a.activity_id=?",id);
            if(rows.isEmpty()) return;
            var row=rows.getFirst();String status=(String)row.get("allocation_status");
            if("PENDING".equals(status)) {
                inventory.allocate(id,(String)row.get("sku_id"),((Number)row.get("total_quantity")).intValue());
                tx.executeWithoutResult(s -> {if(leases.owns("allocation",id,token)) jdbc.update("UPDATE seckill_activity_allocation SET status='READY',last_error=NULL WHERE activity_id=? AND status='PENDING'",id);});
            } else if("CLOSING".equals(status) || ("READY".equals(status) && !now().isBefore(date(row.get("ends_at"))))) {
                // 等所有已受理任务成为确认完成的终态，避免释放尚未锁库的受理请求。
                boolean closing=Boolean.TRUE.equals(tx.execute(s -> {
                    if(!leases.owns("allocation",id,token)) return false;
                    jdbc.queryForMap("SELECT activity_id FROM seckill_activity_v1 WHERE activity_id=? FOR UPDATE",id);
                    int unfinished=jdbc.queryForObject("SELECT COUNT(*) FROM seckill_request_v1 WHERE activity_id=? AND status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED')",Integer.class,id);
                    if(unfinished!=0) {
                        jdbc.update("UPDATE seckill_activity_allocation SET next_attempt_at=? WHERE activity_id=?",now().plusSeconds(10),id);
                        return false;
                    }
                    jdbc.update("UPDATE seckill_activity_allocation SET status='CLOSING',phase_started_at=? WHERE activity_id=? AND status='READY'",now(),id);
                    return true;
                }));
                if(!closing) return;
                inventory.close(id);
                tx.executeWithoutResult(s -> {if(leases.owns("allocation",id,token)) jdbc.update("UPDATE seckill_activity_allocation SET status='CLOSED',last_error=NULL WHERE activity_id=? AND status='CLOSING'",id);});
            }
        } catch(RuntimeException failure) {
            tx.executeWithoutResult(s -> {
                if(!leases.owns("allocation",id,token)) return;
                boolean rejected=failure instanceof org.springframework.web.client.HttpClientErrorException http && http.getStatusCode().is4xxClientError()
                        && http.getStatusCode().value()!=429 && http.getStatusCode().value()!=408;
                jdbc.update("UPDATE seckill_activity_allocation SET status=CASE WHEN status='PENDING' AND ? THEN 'REVIEW' ELSE status END,next_attempt_at=?,last_error=? WHERE activity_id=?",
                        rejected,now().plusSeconds(10),"库存划拨或归还未确认："+failure.getClass().getSimpleName(),id);
            });
            log.warn("活动 {} 库存处理未确认，保留划拨记录",id);
        } finally {leases.release("allocation",id,token);}
    }

    public SeckillSubmitVO submit(SeckillSubmitRequestDTO request) {
        if(request == null) throw bad("request is required");
        text(request.requestId());text(request.accountId());text(request.activityId());text(request.itemId());text(request.skuId());
        if(request.quantity() == null || request.quantity() != 1) throw bad("第一版每账号每活动限购一件");
        var previous = findRequest(request.accountId(),request.requestId());
        if(previous != null) return replay(previous,request);
        Long admitted;
        try { admitted=redis.execute(ADMISSION,List.of("seckill:admission:"+request.activityId()),Integer.toString(admissionLimit)); }
        catch(org.springframework.dao.DataAccessException failure) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"活动暂不可用，请稍后重试");
        }
        if(!Long.valueOf(1).equals(admitted)) throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS,"参与人数较多，请稍后重试");
        try {
            return tx.execute(status -> {
                var activities=jdbc.queryForList("SELECT * FROM seckill_activity_v1 WHERE activity_id = ? FOR UPDATE",request.activityId());
                if(activities.isEmpty()) throw bad("活动不存在");
                var activity=activities.getFirst();
                if(!request.itemId().equals(activity.get("item_id")) || !request.skuId().equals(activity.get("sku_id")))
                    throw bad("商品与活动不匹配");
                var duplicate=jdbc.queryForList("SELECT * FROM seckill_request_v1 WHERE activity_id = ? AND account_id = ?",
                        request.activityId(),request.accountId());
                if(!duplicate.isEmpty()) {
                    if(request.requestId().equals(duplicate.getFirst().get("request_id"))) return replay(duplicate.getFirst(),request);
                    return new SeckillSubmitVO((String)duplicate.getFirst().get("request_id"),"DUPLICATE",
                            (Long)duplicate.getFirst().get("order_id"));
                }
                var starts=date(activity.get("starts_at"));
                var ends=date(activity.get("ends_at"));
                if(now().isBefore(starts)) return new SeckillSubmitVO(request.requestId(),"NOT_STARTED");
                if(!now().isBefore(ends)) return new SeckillSubmitVO(request.requestId(),"ENDED");
                var allocations=jdbc.queryForList("SELECT status FROM seckill_activity_allocation WHERE activity_id=?",request.activityId());
                if(!allocations.isEmpty() && !"READY".equals(allocations.getFirst().get("status")))
                    throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"活动库存尚未确认");
                int deducted=jdbc.update("""
                        UPDATE seckill_activity_v1 SET remaining_quantity=remaining_quantity-1
                        WHERE activity_id=? AND remaining_quantity>0 AND starts_at<=? AND ends_at>?
                        """,request.activityId(),now(),now());
                if(deducted != 1) return new SeckillSubmitVO(request.requestId(),"STOCK_NOT_ENOUGH");
                String eventId=UUID.randomUUID().toString();
                String payload=mapper.writeValueAsString(new Accepted(eventId,request.requestId(),request.accountId(),
                        request.activityId(),request.itemId(),request.skuId(),1,(String)activity.get("item_title"),
                        ((Number)activity.get("unit_price")).longValue(),allocations.isEmpty() ? null : request.activityId()));
                jdbc.update("""
                        INSERT INTO seckill_request_v1(event_id,request_id,account_id,activity_id,item_id,sku_id,payload,status,next_attempt_at,created_at)
                        VALUES (?,?,?,?,?,?,?,'PROCESSING',?,?)
                        """,eventId,request.requestId(),request.accountId(),request.activityId(),request.itemId(),request.skuId(),payload,now(),now());
                return new SeckillSubmitVO(request.requestId(),"PROCESSING");
            });
        } catch(DuplicateKeyException duplicate) {
            previous=findRequest(request.accountId(),request.requestId());
            if(previous != null) return replay(previous,request);
            var rows=jdbc.queryForList("SELECT * FROM seckill_request_v1 WHERE activity_id=? AND account_id=?",request.activityId(),request.accountId());
            if(!rows.isEmpty()) return new SeckillSubmitVO((String)rows.getFirst().get("request_id"),"DUPLICATE",(Long)rows.getFirst().get("order_id"));
            throw duplicate;
        }
    }

    public SeckillSubmitVO result(String accountId,String requestId) {
        text(accountId);text(requestId);
        var row=findRequest(accountId,requestId);
        if(row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"受理记录不存在");
        return new SeckillSubmitVO(requestId,(String)row.get("status"),(Long)row.get("order_id"));
    }

    public void dispatch() {
        if(!dispatchLock.tryLock()) return;
        try {
        var rows=jdbc.queryForList("""
                SELECT event_id,payload FROM seckill_request_v1 WHERE dispatched=FALSE AND order_id IS NULL
                AND status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED','REVIEW_REQUIRED') AND next_attempt_at<=?
                ORDER BY next_attempt_at,event_id LIMIT ?
                """,now(),batchSize);
        runBatch(publishers,rows,this::dispatchOne);
        } finally { dispatchLock.unlock(); }
    }
    private void dispatchOne(Map<String,Object> row) {
            String id=(String)row.get("event_id");
            String token=leases.acquire("seckill-publish",id);if(token==null) return;
            try {
            // 扫描与认领之间可能已被另一个实例完成；认领后重新检查。
            int due=jdbc.queryForObject("SELECT COUNT(*) FROM seckill_request_v1 WHERE event_id=? AND dispatched=FALSE AND order_id IS NULL AND status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED','REVIEW_REQUIRED') AND next_attempt_at<=?",Integer.class,id,now());
            if(due!=1) return;
            try {
                kafka.send("checkout-seckill-accepted",id,(String)row.get("payload")).get(3,TimeUnit.SECONDS);
                tx.executeWithoutResult(s -> {
                if(!leases.owns("seckill-publish",id,token)) return;
                jdbc.update("""
                        UPDATE seckill_request_v1 SET dispatched=TRUE,published_at=?,last_error=NULL
                        WHERE event_id=? AND status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED','REVIEW_REQUIRED')
                        """,now(),id);
                });
            } catch(InterruptedException interrupted) {
                Thread.currentThread().interrupt(); return;
            } catch(Exception failure) {
                // 发送结果未知时保留原事件；不回补，重发由下游业务幂等吸收。
                tx.executeWithoutResult(s -> {
                if(!leases.owns("seckill-publish",id,token)) return;
                jdbc.update("""
                        UPDATE seckill_request_v1 SET attempts=attempts+1,next_attempt_at=?,last_error=? WHERE event_id=? AND dispatched=FALSE
                        AND status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED','REVIEW_REQUIRED')
                        """,now().plusSeconds(5),"消息待重试",id);
                });
                log.warn("秒杀事件 {} 发布未确认，将使用原事件重试",id);
                return;
            }
            } finally {leases.release("seckill-publish",id,token);}
    }

    public void reconcile() {
        if(!reconcileLock.tryLock()) return;
        try {
        var rows=jdbc.queryForList("""
                SELECT event_id,account_id FROM seckill_request_v1 WHERE status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED')
                AND next_attempt_at<=? ORDER BY next_attempt_at,event_id LIMIT ?
                """,now(),batchSize);
        runBatch(reconcilers,rows,this::reconcileOne);
        } finally { reconcileLock.unlock(); }
    }
    private void reconcileOne(Map<String,Object> row) {
            String id=(String)row.get("event_id");
            String token=leases.acquire("seckill-reconcile",id);if(token==null) return;
            try {
            int due=jdbc.queryForObject("SELECT COUNT(*) FROM seckill_request_v1 WHERE event_id=? AND status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED') AND next_attempt_at<=?",Integer.class,id,now());
            if(due!=1) return;
            try {
                var result=orders.result(id,(String)row.get("account_id"));
                tx.executeWithoutResult(s -> {if(leases.owns("seckill-reconcile",id,token)) jdbc.update("UPDATE seckill_request_v1 SET next_attempt_at=? WHERE event_id=? AND dispatched=TRUE",now().plusSeconds(5),id);});
                if(result == null) {
                    redriveMissing(id,token);
                    return;
                }
                tx.executeWithoutResult(txStatus -> {
                    if(!leases.owns("seckill-reconcile",id,token)) return;
                    var stored=jdbc.queryForMap("SELECT * FROM seckill_request_v1 WHERE event_id=? FOR UPDATE",id);
                    String current=(String)stored.get("status");
                    // HTTP 查询发生在事务外；其他实例可能已推进，迟到结果不能覆盖终态或让进度回退。
                    if(TERMINAL.contains(current)) return;
                    boolean failed=List.of("CREATION_FAILED","CANCELED","TIMEOUT_CLOSED").contains(result.status());
                    boolean complete=List.of("DONE","FAILED").contains(result.phase());
                    String state=result.status().equals("CREATION_FAILED") ? "FAILED" : result.status();
                    if(!List.of("CREATING","WAITING_PAYMENT","PAID","FAILED","CANCELED","TIMEOUT_CLOSED","REFUNDING","REFUNDED").contains(state))
                        throw new IllegalStateException("未知订单状态");
                    if("WAITING_PAYMENT".equals(current) && "CREATING".equals(state)) return;
                    if(stored.get("order_id")!=null && ((Number)stored.get("order_id")).longValue()!=result.orderId())
                        throw new IllegalStateException("同一事件对应不同订单");
                    if(failed && !complete) return;
                    if(failed && !Boolean.TRUE.equals(stored.get("quota_released"))) {
                        jdbc.update("UPDATE seckill_activity_v1 SET remaining_quantity=remaining_quantity+1 WHERE activity_id=?",stored.get("activity_id"));
                        jdbc.update("UPDATE seckill_request_v1 SET quota_released=TRUE WHERE event_id=?",id);
                    }
                    jdbc.update("UPDATE seckill_request_v1 SET status=?,order_id=? WHERE event_id=?",state,result.orderId(),id);
                });
            } catch(RuntimeException failure) {
                tx.executeWithoutResult(s -> {if(leases.owns("seckill-reconcile",id,token)) jdbc.update("UPDATE seckill_request_v1 SET next_attempt_at=? WHERE event_id=? AND dispatched=TRUE",now().plusSeconds(5),id);});
                log.warn("秒杀事件 {} 暂无法查询最终订单，保留原受理记录",id);
                return;
            }
            } finally {leases.release("seckill-reconcile",id,token);}
    }

    private void redriveMissing(String id,String token) {
        // attempts 统计发布失败与无订单重投；发布故障继续重试，仅对已发布但长期无订单停止自动重投。
        tx.executeWithoutResult(s -> {
            if(!leases.owns("seckill-reconcile",id,token)) return;
            var row=jdbc.queryForMap("SELECT * FROM seckill_request_v1 WHERE event_id=? FOR UPDATE",id);
            if(TERMINAL.contains(row.get("status")) || "REVIEW_REQUIRED".equals(row.get("status"))
                    || row.get("order_id")!=null || !Boolean.TRUE.equals(row.get("dispatched"))) return;
            var published=row.get("published_at");
            if(published==null || date(published).isAfter(now().minusSeconds(60))) return;
            int attempts=((Number)row.get("attempts")).intValue();
            if(attempts>=maxRedrives) {
                jdbc.update("UPDATE seckill_request_v1 SET status='REVIEW_REQUIRED',last_error=? WHERE event_id=?",
                        "已发布但持续无订单，请检查死信与下游服务",id);
                log.error("秒杀事件 {} 持续无订单，已暂停自动重投，需人工核对",id);
            } else {
                jdbc.update("UPDATE seckill_request_v1 SET dispatched=FALSE,attempts=attempts+1,last_error=? WHERE event_id=?",
                        "已发布但暂未找到订单，按原事件重投",id);
            }
        });
    }

    public List<TaskView> stalledTasks(int minimumAgeSeconds) {
        if(minimumAgeSeconds<0 || minimumAgeSeconds>86400*30) throw bad("查询年龄范围不合法");
        return jdbc.query("""
                SELECT * FROM seckill_request_v1 WHERE status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED')
                AND created_at<=? ORDER BY created_at LIMIT 100
                """,(r,n)->new TaskView(r.getString("event_id"),r.getString("request_id"),r.getString("activity_id"),
                r.getString("status"),r.getObject("order_id",Long.class),r.getInt("attempts"),r.getString("last_error"),
                r.getObject("created_at",LocalDateTime.class).toInstant(ZoneOffset.UTC),
                r.getObject("next_attempt_at",LocalDateTime.class).toInstant(ZoneOffset.UTC)),now().minusSeconds(minimumAgeSeconds));
    }

    public Map<String,Long> taskSummary() {
        var summary=jdbc.queryForObject("""
                SELECT COUNT(*) AS pending,
                COALESCE(SUM(CASE WHEN dispatched=FALSE AND order_id IS NULL AND status<>'REVIEW_REQUIRED' THEN 1 ELSE 0 END),0) AS unpublished,
                COALESCE(SUM(CASE WHEN status='REVIEW_REQUIRED' THEN 1 ELSE 0 END),0) AS review_count
                FROM seckill_request_v1 WHERE status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED')
                """,(r,n)->Map.of("pending",r.getLong("pending"),"unpublished",r.getLong("unpublished"),"reviewRequired",r.getLong("review_count")));
        var allocations=jdbc.queryForObject("SELECT COUNT(*) AS pending,COALESCE(SUM(CASE WHEN status='REVIEW' THEN 1 ELSE 0 END),0) AS review_count FROM seckill_activity_allocation WHERE status IN ('PENDING','REVIEW','CLOSING')",
                (r,n)->Map.of("pending",r.getLong("pending"),"review",r.getLong("review_count")));
        return Map.of("pending",summary.get("pending"),"unpublished",summary.get("unpublished"),
                "reviewRequired",summary.get("reviewRequired")+allocations.get("review"),"pendingAllocations",allocations.get("pending"));
    }

    public List<Map<String,Object>> allocationTasks() {
        return jdbc.queryForList("SELECT activity_id,status,next_attempt_at,last_error FROM seckill_activity_allocation WHERE status IN ('PENDING','REVIEW','CLOSING') ORDER BY next_attempt_at LIMIT 100");
    }
    public void retryAllocation(String id,OperatorAction action) {
        text(id);validateAction(action);
        tx.executeWithoutResult(s -> {
            if(jdbc.update("UPDATE seckill_activity_allocation SET status='PENDING',next_attempt_at=?,phase_started_at=?,last_error=NULL WHERE activity_id=? AND status='REVIEW'",now(),now(),id)!=1)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"仅可恢复待核对的活动划拨");
            jdbc.update("INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at) VALUES ('allocation',?,?,'RETRY',?,?)",id,action.operatorId(),action.reason(),now());
        });
    }
    private static void validateAction(OperatorAction action) {
        if(action==null) throw bad("操作人和原因不能为空");text(action.operatorId());
        if(action.reason()==null || action.reason().isBlank() || action.reason().length()>255) throw bad("恢复原因不合法");
    }

    public void retryTask(String eventId,OperatorAction action) {
        text(eventId);
        validateAction(action);
        tx.executeWithoutResult(s -> {
        int changed=jdbc.update("""
                UPDATE seckill_request_v1 SET status='PROCESSING',dispatched=FALSE,attempts=0,last_error=NULL,next_attempt_at=?
                WHERE event_id=? AND status='REVIEW_REQUIRED' AND order_id IS NULL
                """,now(),eventId);
        if(changed!=1) throw new ResponseStatusException(HttpStatus.CONFLICT,"仅可重试待核对且未关联订单的任务");
        jdbc.update("""
                INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at)
                VALUES ('seckill',?,?,'RETRY',?,?)
                """,eventId,action.operatorId(),action.reason(),now());
        });
        log.info("秒杀事件 {} 已由内部运维接口恢复重投，保留原事件与额度",eventId);
    }

    private java.util.Map<String,Object> findRequest(String accountId,String requestId) {
        var rows=jdbc.queryForList("SELECT * FROM seckill_request_v1 WHERE account_id=? AND request_id=?",accountId,requestId);
        return rows.isEmpty()?null:rows.getFirst();
    }
    private SeckillSubmitVO replay(java.util.Map<String,Object> row,SeckillSubmitRequestDTO request) {
        if(!request.activityId().equals(row.get("activity_id")) || !request.itemId().equals(row.get("item_id"))
                || !request.skuId().equals(row.get("sku_id"))) throw new ResponseStatusException(HttpStatus.CONFLICT,"幂等键参数冲突");
        return new SeckillSubmitVO(request.requestId(),(String)row.get("status"),(Long)row.get("order_id"));
    }
    private LocalDateTime now(){return LocalDateTime.now(clock);}
    private static LocalDateTime date(Object value) {
        if(value instanceof LocalDateTime local) return local;
        if(value instanceof java.sql.Timestamp timestamp) return timestamp.toLocalDateTime();
        throw new IllegalStateException("不支持的数据库时间类型");
    }
    private static void text(String value) {
        if(value == null || value.isBlank() || value.length()>64 || !value.equals(value.trim())) throw bad("标识不合法");
    }
    private static ResponseStatusException bad(String message){return new ResponseStatusException(HttpStatus.BAD_REQUEST,message);}
}
