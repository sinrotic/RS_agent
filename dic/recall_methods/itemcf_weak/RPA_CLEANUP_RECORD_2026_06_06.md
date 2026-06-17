# itemcf_weak RPA å®žéªŒç»“æžœæ¸…ç�†è®°å½•ï¼ˆ2026-06-06ï¼‰

## æ¸…ç�†åŽŸåˆ™

- åˆ é™¤å·²è¢«åˆ¤å®šæ•ˆæžœä¸�ä½³æˆ–é‡�å¤�çš„ä¸€æ¬¡æ€§ RPA/RPA-paper-faithful ç»“æžœç›®å½•ã€�æ—¥å¿—å’Œä¸´æ—¶è„šæœ¬ã€‚
- ä¿�ç•™å½“å‰�æ²»ç�†æˆ–å¯¹ç…§ä»�éœ€è¦�çš„ canonical artifactï¼š`rpa_lite_diagnostic_replay_v1`ã€�è¿œç¨‹ v1 åˆ†ç‰‡è¯Šæ–­æŠ¥å‘Šã€�v2 confidence best ç»“æžœã€‚
- v4 paper-binary p500 ä»�åœ¨è¿œç¨‹è¿�è¡Œï¼Œä¿�ç•™æœ¬åœ°å�¯åŠ¨è„šæœ¬ï¼Œå¾…å®Œæˆ�å�Žå†�æŒ‰æ•ˆæžœå†³å®šæ˜¯å�¦æ¸…ç�†ã€‚
- æ‰€æœ‰å®žéªŒä»�ä¸º `DIAGNOSTIC_ONLY`ï¼Œä¸�æ‰“å¼€ candidate generation / promotionã€‚

- æ¸…ç�†æ—¶é—´ï¼š`2026-06-06T03:05:49.105111+00:00`
- é‡Šæ”¾ç©ºé—´ï¼š`0.767 MB`

## å·²åˆ é™¤

- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_local_10gb_v1` â€” dir, 0.014 MB, files=1
  - è®°å½•æŒ‡æ ‡ï¼š`{"best_variant": "rpa_iuf_sparse_medium_p100_user500_local10gb", "candidate_count_stats": {"max": 100, "min": 0, "p50": 100.0, "p90": 100.0}, "candidate_user_rate": 0.930422, "completed_shards": null, "in_universe_recall@500": 0.048733, "peak_observed_rss_gb_max": null, "raw_hit_user_rate@500": 0.034789, "raw_recall@500": 0.02713, "schema_version": "pool500_itemcf_weak_rpa_lite_local_10gb_v1", "status": "PASS"}`
- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_local_10gb_sharded_v1` â€” dir, 0.373 MB, files=22
  - è®°å½•æŒ‡æ ‡ï¼š`{"best_variant": "rpa_iuf_sparse_medium_p100_user500_sharded10gb", "candidate_count_stats": {"max": 100, "min": 0, "p50": 100.0, "p90": 100.0}, "candidate_user_rate": 0.928158, "completed_shards": 20, "in_universe_recall@500": 0.050346, "peak_observed_rss_gb_max": 5.5056, "raw_hit_user_rate@500": 0.032857, "raw_recall@500": 0.026407, "schema_version": "pool500_itemcf_weak_rpa_lite_local_10gb_sharded_v1", "status": "PASS"}`
- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_v3_paper_faithful_local10gb_seq_v1` â€” dir, 0.246 MB, files=10
- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_v3_paper_faithful_remote_no_mem_limit_4jobs_v1` â€” dir, 0.023 MB, files=1
  - è®°å½•æŒ‡æ ‡ï¼š`{"best_variant": "rpa_v1_raw_propagation_p100_reference", "candidate_count_stats": {"max": 100, "min": 0, "p50": 100.0, "p90": 100.0}, "candidate_user_rate": 0.928158, "completed_shards": 20, "in_universe_recall@500": 0.050346, "peak_observed_rss_gb_max": 9.6066, "raw_hit_user_rate@500": 0.032857, "raw_recall@500": 0.026407, "schema_version": "pool500_itemcf_weak_rpa_lite_paper_faithful_sharded_v1", "status": "PASS"}`
- `.omc/logs/rpa_lite_v3_paper_faithful_local10gb_seq_v1` â€” dir, 0.032 MB, files=12
- `.omc/logs/rpa_lite_v3_paper_faithful_remote_no_mem_limit_4jobs_v1` â€” dir, 0.001 MB, files=1
- `.omc/run_rpa_lite_v3_paper_faithful_sharded.py` â€” file, 0.036 MB, files=1
- `.omc/run_rpa_lite_v3_paper_faithful_remote_no_mem_limit.py` â€” file, 0.036 MB, files=1
- `.omc/run_rpa_v3_remote_driver.py` â€” file, 0.003 MB, files=1
- `.omc/run_rpa_v3_remote_no_mem_limit_driver.py` â€” file, 0.003 MB, files=1

## ä¿�ç•™

- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_diagnostic_replay_v1` â€” exists=True, 0.029 MB, files=6
- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_local_10gb_sharded_remote_v1` â€” exists=True, 0.072 MB, files=23
  - è®°å½•æŒ‡æ ‡ï¼š`{"best_variant": "rpa_iuf_sparse_medium_p100_user500_sharded10gb", "candidate_count_stats": {"max": 100, "min": 0, "p50": 100.0, "p90": 100.0}, "candidate_user_rate": 0.928158, "completed_shards": 20, "in_universe_recall@500": 0.050346, "peak_observed_rss_gb_max": 6.8637, "raw_hit_user_rate@500": 0.032857, "raw_recall@500": 0.026407, "schema_version": "pool500_itemcf_weak_rpa_lite_local_10gb_sharded_v1", "status": "PASS"}`
- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_v2_confidence_gate_local10gb_seq_v1` â€” exists=True, 0.532 MB, files=21
  - è®°å½•æŒ‡æ ‡ï¼š`{"best_variant": "rpa_v2_confidence_depth_decay_p100", "candidate_count_stats": {"max": 100, "min": 0, "p50": 100.0, "p90": 100.0}, "candidate_user_rate": 0.928158, "completed_shards": 20, "in_universe_recall@500": 0.051538, "peak_observed_rss_gb_max": 7.4879, "raw_hit_user_rate@500": 0.033506, "raw_recall@500": 0.026923, "schema_version": "pool500_itemcf_weak_rpa_lite_local_10gb_sharded_v2", "status": "PASS"}`
- `.omc/run_rpa_lite_v2_confidence_gate_sharded.py` â€” exists=True, 0.032 MB, files=1
- `.omc/run_rpa_lite_v4_paper_binary_p500_remote_no_mem_limit.py` â€” exists=True, 0.036 MB, files=1
- `.omc/run_rpa_v4_paper_binary_p500_remote_driver.py` â€” exists=True, 0.003 MB, files=1

## ç»“è®º

- v3 paper-faithful depth1 åœ¨ bounded candidate replay ä¸‹æ²¡æœ‰è¶…è¿‡ v2 confidence/path-supportï¼›å…¶ç»“æžœç›®å½•å·²åˆ é™¤ï¼Œä»…ä¿�ç•™æœ¬è®°å½•ã€‚
- é¢�å¤– IDF sensitivity æ˜Žæ˜¾ä¼¤å®³ recallï¼Œä¸�å†�ä½œä¸ºä¸»çº¿ä¿�ç•™ã€‚
- å½“å‰�æœ¬åœ°ä¿�ç•™çš„æœ€ä½³ itemcf_weak RPA è¯Šæ–­ç»“æžœä»�æ˜¯ `rpa_lite_v2_confidence_gate_local10gb_seq_v1`ï¼›canonical governance artifact ä»�æ˜¯ `rpa_lite_diagnostic_replay_v1`ã€‚
