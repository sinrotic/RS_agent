package com.sinrotic.rs.promotion;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

import java.time.Clock;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

@Service
public class PromotionService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final Clock clock;

    @org.springframework.beans.factory.annotation.Autowired
    public PromotionService(JdbcTemplate jdbc, PlatformTransactionManager manager) {
        this(jdbc, manager, Clock.systemUTC());
    }

    public PromotionService(JdbcTemplate jdbc, PlatformTransactionManager manager, Clock clock) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(manager);
        this.clock = clock;
    }

    public record Campaign(String campaignId, String title, String itemId, int totalQuantity,
                           int remainingQuantity, long minimumAmount, long discountAmount,
                           LocalDateTime startsAt, LocalDateTime endsAt, LocalDateTime expiresAt) {}
    public record Coupon(String couponId, String campaignId, String accountId, String requestId,
                         String status, Long lockedOrderId, String title, String itemId,
                         long minimumAmount, long discountAmount, LocalDateTime expiresAt) {}
    public record LockRequest(Long orderId, String couponId, String accountId, String itemId, Long originalAmount) {}
    public record Reservation(Long orderId, String couponId, String accountId, String itemId,
                              long originalAmount, long discountAmount, String status) {}

    public void createCampaign(Campaign c) {
        if (c == null) throw bad("活动不能为空");
        text(c.campaignId());
        if (c.title() == null || c.title().isBlank() || c.title().length() > 160 || c.totalQuantity() <= 0 || c.discountAmount() <= 0
                || c.minimumAmount() <= c.discountAmount() || c.startsAt() == null || c.endsAt() == null
                || c.expiresAt() == null || !c.startsAt().isBefore(c.endsAt()) || c.endsAt().isAfter(c.expiresAt()))
            throw bad("活动额度、金额或有效期不合法");
        if (c.itemId() != null) text(c.itemId());
        var starts=c.startsAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
        var ends=c.endsAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
        var expires=c.expiresAt().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
        if(!starts.isBefore(ends) || ends.isAfter(expires)) throw bad("活动时间精度必须满足数据库微秒边界");
        jdbc.update("""
                INSERT INTO promotion_campaign
                (campaign_id,title,item_id,total_quantity,remaining_quantity,minimum_amount,discount_amount,starts_at,ends_at,expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """, c.campaignId(), c.title(), c.itemId(), c.totalQuantity(), c.totalQuantity(),
                c.minimumAmount(), c.discountAmount(), starts, ends, expires);
    }

    public List<Campaign> campaigns(String itemId) {
        text(itemId);
        return jdbc.query("""
                SELECT * FROM promotion_campaign WHERE (item_id IS NULL OR item_id = ?)
                AND starts_at <= ? AND ends_at > ? ORDER BY ends_at, campaign_id LIMIT 100
                """, (r, n) -> new Campaign(r.getString("campaign_id"), r.getString("title"), r.getString("item_id"),
                r.getInt("total_quantity"), r.getInt("remaining_quantity"), r.getLong("minimum_amount"),
                r.getLong("discount_amount"), r.getObject("starts_at",LocalDateTime.class),
                r.getObject("ends_at",LocalDateTime.class), r.getObject("expires_at",LocalDateTime.class)),
                itemId, now(), now());
    }

    public Coupon claim(String accountId, String campaignId, String requestId) {
        text(accountId); text(campaignId); text(requestId);
        try {
            return tx.execute(status -> {
                Coupon previous = byRequest(accountId, requestId);
                if (previous != null) return equivalentClaim(previous, campaignId);
                // 活动行只在单次领取事务中锁定；配额和个人券一起提交。
                var campaigns = jdbc.queryForList("SELECT campaign_id FROM promotion_campaign WHERE campaign_id = ? FOR UPDATE", campaignId);
                if (campaigns.isEmpty()) throw missing("活动不存在");
                previous = byRequest(accountId, requestId);
                if (previous != null) return equivalentClaim(previous, campaignId);
                var owned = coupons("c.account_id = ? AND c.campaign_id = ?", accountId, campaignId);
                if (!owned.isEmpty()) {
                    rememberClaim(accountId,requestId,owned.getFirst().couponId());
                    return owned.getFirst();
                }
                int changed = jdbc.update("""
                        UPDATE promotion_campaign SET remaining_quantity = remaining_quantity - 1
                        WHERE campaign_id = ? AND remaining_quantity > 0 AND starts_at <= ? AND ends_at > ?
                        """, campaignId, now(), now());
                if (changed != 1) throw conflict("活动未开始、已结束或优惠券已领完");
                String id = UUID.randomUUID().toString();
                jdbc.update("""
                        INSERT INTO promotion_coupon(coupon_id,campaign_id,account_id,request_id,status,created_at)
                        VALUES (?,?,?,?,'AVAILABLE',?)
                        """, id, campaignId, accountId, requestId, now());
                rememberClaim(accountId,requestId,id);
                return coupons("c.coupon_id = ?", id).getFirst();
            });
        } catch (DuplicateKeyException duplicate) {
            Coupon previous = byRequest(accountId, requestId);
            if (previous != null) return equivalentClaim(previous, campaignId);
            var owned = coupons("c.account_id = ? AND c.campaign_id = ?", accountId, campaignId);
            if (!owned.isEmpty()) {
                // 不同幂等键并发领取同一活动：原领取额度已回滚，补记本次键与既有券的绑定。
                try { rememberClaim(accountId,requestId,owned.getFirst().couponId()); }
                catch (DuplicateKeyException raced) { return equivalentClaim(byRequest(accountId,requestId),campaignId); }
                return owned.getFirst();
            }
            throw duplicate;
        }
    }

    public List<Coupon> wallet(String accountId) {
        text(accountId);
        return coupons("c.account_id = ?", accountId);
    }
    public com.sinrotic.rs.common.commerce.CommerceInput.Page<Coupon> walletPage(String accountId,String afterId,int limit) {
        text(accountId);com.sinrotic.rs.common.commerce.CommerceInput.limit(limit);
        if(afterId!=null) text(afterId);
        var found=queryCoupons("c.account_id=? AND c.coupon_id>? ORDER BY c.coupon_id LIMIT ?",accountId,afterId==null ? "" : afterId,limit+1);
        boolean more=found.size()>limit;var items=more ? found.subList(0,limit) : found;
        return new com.sinrotic.rs.common.commerce.CommerceInput.Page<>(items,more ? items.getLast().couponId() : null);
    }
    public void refund(long orderId,String couponId) {
        text(couponId);
        tx.executeWithoutResult(s -> {
            if(jdbc.queryForList("SELECT coupon_id FROM promotion_coupon WHERE coupon_id=? FOR UPDATE",couponId).isEmpty()) throw missing("优惠券不存在");
            var reservation=reservation(orderId);
            if(reservation==null || !couponId.equals(reservation.couponId())) throw conflict("找不到对应核销记录");
            if("REFUNDED".equals(reservation.status())) return;
            if(!"USED".equals(reservation.status())) throw conflict("只能退还已核销的优惠券");
            var coupon=coupons("c.coupon_id=?",couponId).getFirst();
            if(!"USED".equals(coupon.status())) throw conflict("优惠券状态不一致");
            jdbc.update("UPDATE promotion_coupon SET status=?,locked_order_id=NULL WHERE coupon_id=?",now().isBefore(coupon.expiresAt()) ? "AVAILABLE" : "EXPIRED",couponId);
            jdbc.update("UPDATE promotion_reservation SET status='REFUNDED',updated_at=? WHERE order_id=?",now(),orderId);
        });
    }

    public Reservation lock(LockRequest request) {
        if (request == null || request.orderId() == null || request.orderId() <= 0
                || request.originalAmount() == null || request.originalAmount() <= 0) throw bad("锁券参数不合法");
        text(request.couponId()); text(request.accountId()); text(request.itemId());
        return tx.execute(status -> {
            var rows = jdbc.queryForList("SELECT coupon_id FROM promotion_coupon WHERE coupon_id = ? FOR UPDATE", request.couponId());
            if (rows.isEmpty()) throw missing("优惠券不存在");
            Reservation previous = reservation(request.orderId());
            if (previous != null) {
                if (!previous.couponId().equals(request.couponId()) || !previous.accountId().equals(request.accountId())
                        || !previous.itemId().equals(request.itemId()) || previous.originalAmount() != request.originalAmount())
                    throw conflict("订单锁券参数与原请求不一致");
                if ("RELEASED".equals(previous.status())) throw conflict("本订单的优惠券预留已经释放");
                return previous;
            }
            Coupon coupon = coupons("c.coupon_id = ?", request.couponId()).getFirst();
            if (!coupon.accountId().equals(request.accountId())) throw missing("优惠券不存在");
            if (!"AVAILABLE".equals(coupon.status()) || !now().isBefore(coupon.expiresAt())
                    || (coupon.itemId() != null && !coupon.itemId().equals(request.itemId()))
                    || request.originalAmount() < coupon.minimumAmount()) throw conflict("优惠券不可用或不满足使用条件");
            jdbc.update("UPDATE promotion_coupon SET status = 'LOCKED', locked_order_id = ? WHERE coupon_id = ?",
                    request.orderId(), request.couponId());
            jdbc.update("""
                    INSERT INTO promotion_reservation(order_id,coupon_id,account_id,item_id,original_amount,discount_amount,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,'RESERVED',?,?)
                    """, request.orderId(), request.couponId(), request.accountId(), request.itemId(),
                    request.originalAmount(), coupon.discountAmount(), now(), now());
            return reservation(request.orderId());
        });
    }

    public void finish(long orderId, String couponId, boolean confirm) {
        text(couponId);
        tx.executeWithoutResult(status -> {
            var rows = jdbc.queryForList("SELECT coupon_id FROM promotion_coupon WHERE coupon_id = ? FOR UPDATE", couponId);
            if (rows.isEmpty()) throw missing("优惠券不存在");
            Reservation reservation = reservation(orderId);
            if (reservation == null || !reservation.couponId().equals(couponId)) throw conflict("找不到对应锁券记录");
            String target = confirm ? "USED" : "RELEASED";
            if (target.equals(reservation.status())) return;
            if (!"RESERVED".equals(reservation.status())) throw conflict("优惠券预留已进入另一终态");
            Coupon coupon = coupons("c.coupon_id = ?", couponId).getFirst();
            if (!Objects.equals(coupon.lockedOrderId(), orderId) || !"LOCKED".equals(coupon.status()))
                throw conflict("优惠券锁定订单不匹配");
            // 锁券时有效即可在订单支付期限内核销；取消时按原有效期决定是否还能使用。
            String couponState = confirm ? "USED" : now().isBefore(coupon.expiresAt()) ? "AVAILABLE" : "EXPIRED";
            jdbc.update("UPDATE promotion_coupon SET status = ?, locked_order_id = NULL WHERE coupon_id = ?", couponState, couponId);
            jdbc.update("UPDATE promotion_reservation SET status = ?, updated_at = ? WHERE order_id = ?", target, now(), orderId);
        });
    }

    /** 即使锁券响应丢失或请求尚未到达，也能持久取消该订单的预留。 */
    public void cancel(LockRequest request) {
        if (request == null || request.orderId() == null || request.orderId() <= 0
                || request.originalAmount() == null || request.originalAmount() <= 0) throw bad("取消锁券参数不合法");
        text(request.couponId()); text(request.accountId()); text(request.itemId());
        tx.executeWithoutResult(status -> {
            var rows = jdbc.queryForList("SELECT coupon_id FROM promotion_coupon WHERE coupon_id = ? FOR UPDATE",request.couponId());
            if (rows.isEmpty()) return; // 不存在的券没有本订单可释放的资源。
            Coupon coupon = coupons("c.coupon_id = ?",request.couponId()).getFirst();
            if (!coupon.accountId().equals(request.accountId())) return;
            Reservation previous = reservation(request.orderId());
            if (previous != null) {
                if (!previous.couponId().equals(request.couponId()) || !previous.accountId().equals(request.accountId())
                        || !previous.itemId().equals(request.itemId()) || previous.originalAmount() != request.originalAmount())
                    throw conflict("订单取消锁券参数与原请求不一致");
                finish(request.orderId(),request.couponId(),false);
                return;
            }
            jdbc.update("""
                    INSERT INTO promotion_reservation(order_id,coupon_id,account_id,item_id,original_amount,discount_amount,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,0,'RELEASED',?,?)
                    """,request.orderId(),request.couponId(),request.accountId(),request.itemId(),request.originalAmount(),now(),now());
        });
    }

    private Reservation reservation(long orderId) {
        var rows = jdbc.query("SELECT * FROM promotion_reservation WHERE order_id = ?", (r, n) ->
                new Reservation(r.getLong("order_id"), r.getString("coupon_id"), r.getString("account_id"),
                        r.getString("item_id"), r.getLong("original_amount"), r.getLong("discount_amount"),
                        r.getString("status")), orderId);
        return rows.isEmpty() ? null : rows.getFirst();
    }
    private Coupon byRequest(String accountId, String requestId) {
        var rows = coupons("c.coupon_id IN (SELECT coupon_id FROM promotion_claim_request WHERE account_id = ? AND request_id = ?)", accountId, requestId);
        return rows.isEmpty() ? null : rows.getFirst();
    }
    private void rememberClaim(String accountId,String requestId,String couponId) {
        jdbc.update("INSERT INTO promotion_claim_request(account_id,request_id,coupon_id) VALUES (?,?,?)",accountId,requestId,couponId);
    }
    private Coupon equivalentClaim(Coupon coupon, String campaignId) {
        if (!coupon.campaignId().equals(campaignId)) throw conflict("幂等键已用于另一活动");
        return coupon;
    }
    private List<Coupon> coupons(String where, Object... args) {
        return queryCoupons(where+" ORDER BY c.created_at DESC, c.coupon_id LIMIT 200",args);
    }
    private List<Coupon> queryCoupons(String suffix,Object... args) {
        return jdbc.query("""
                SELECT c.*, p.title,p.item_id,p.minimum_amount,p.discount_amount,p.expires_at
                FROM promotion_coupon c JOIN promotion_campaign p ON p.campaign_id = c.campaign_id WHERE
                """ + suffix, (r, n) -> {
            String state = r.getString("status");
            LocalDateTime expiry = r.getObject("expires_at",LocalDateTime.class);
            if ("AVAILABLE".equals(state) && !now().isBefore(expiry)) state = "EXPIRED";
            return new Coupon(r.getString("coupon_id"), r.getString("campaign_id"), r.getString("account_id"),
                    r.getString("request_id"), state, r.getObject("locked_order_id", Long.class), r.getString("title"),
                    r.getString("item_id"), r.getLong("minimum_amount"), r.getLong("discount_amount"), expiry);
        }, args);
    }
    private LocalDateTime now() { return LocalDateTime.now(clock); }
    private static void text(String value) {
        if (value == null || value.isBlank() || value.length() > 64 || !value.equals(value.trim())) throw bad("标识不能为空、不能包含首尾空格且不能超过 64 字符");
    }
    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST, message); }
    private static ResponseStatusException missing(String message) { return new ResponseStatusException(HttpStatus.NOT_FOUND, message); }
    private static ResponseStatusException conflict(String message) { return new ResponseStatusException(HttpStatus.CONFLICT, message); }
}
