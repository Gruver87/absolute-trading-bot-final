/// Hot-path score. Same gates as spotbot.analyzer._score_python.
/// Returns 0 to refuse. Prices and sizes are integers; there is no float.

#[no_mangle]
pub extern "C" fn sb_score(
    volume_bps: i32,
    close_pos_bps: i32,
    oracle_dev_bps: i32,
    rsi_value: i32,
    bid: i64,
    ask: i64,
) -> i32 {
    if bid <= 0 || ask < 0 || ask >= bid {
        return 0;
    }
    if volume_bps < 20_000 || close_pos_bps < 6_500 {
        return 0;
    }
    if oracle_dev_bps < 0 || oracle_dev_bps > 30 {
        return 0;
    }
    let mut total: i32 = 4_000 + 2_000 + 3_000;
    if (0..45).contains(&rsi_value) {
        total += 1_000;
    }
    total
}
