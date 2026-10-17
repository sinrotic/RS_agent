package com.sinrotic.rs.common.commerce;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.UUID;

/** 远程调用在事务外；提交本地进度前须在同一事务锁定并验证租约。 */
public final class WorkerLeaseStore {
    private final JdbcTemplate jdbc;
    public WorkerLeaseStore(JdbcTemplate jdbc) { this.jdbc=jdbc; }
    public String acquire(String type,String id) {
        try { jdbc.update("INSERT INTO commerce_worker_lease(worker_type,resource_id) VALUES (?,?)",type,id); }
        catch(DuplicateKeyException existing) { /* 已登记的任务按过期条件争抢。 */ }
        String token=UUID.randomUUID().toString();
        int changed=jdbc.update("""
                UPDATE commerce_worker_lease SET claim_token=?,lease_until=TIMESTAMPADD(SECOND,90,CURRENT_TIMESTAMP(6))
                WHERE worker_type=? AND resource_id=? AND (claim_token IS NULL OR lease_until<=CURRENT_TIMESTAMP(6))
                """,token,type,id);
        return changed==1 ? token : null;
    }
    public boolean owns(String type,String id,String token) {
        // 当前读并锁住租约，防止验证后被新实例领取；调用者须处于进度提交事务内。
        var rows=jdbc.queryForList("""
                SELECT claim_token FROM commerce_worker_lease WHERE worker_type=? AND resource_id=?
                AND lease_until>CURRENT_TIMESTAMP(6) FOR UPDATE
                """,type,id);
        return !rows.isEmpty() && token.equals(rows.getFirst().get("claim_token"));
    }
    public void release(String type,String id,String token) {
        jdbc.update("UPDATE commerce_worker_lease SET claim_token=NULL,lease_until=NULL WHERE worker_type=? AND resource_id=? AND claim_token=?",type,id,token);
    }
}
