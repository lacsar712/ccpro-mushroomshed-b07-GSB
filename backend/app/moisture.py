"""采收扣水(去湿)展示公式。

全项目唯一实现:采收列表、采收单条、Dashboard 近 7 日公斤都调用
``moisture_kg_for_harvest``,任何地方不得另写一套。

规则:
- 取同室 ``recordedAt <= harvestedAt`` 且间隔不超过 180 分钟的最近一条 ClimateLog;
  找不到 → 409,正文带 ``roomId``。
- 该记录 ``humidityPct >= 92``:``moistureKg = weightKg * 0.96``。
- ``85 <= humidityPct < 92``:``moistureKg = weightKg``(不扣)。
- ``humidityPct < 85``:禁止展示,409,正文带 ``climateLogId``。
"""

from datetime import datetime, timedelta
from typing import Optional

from app.models.climate_log import ClimateLog

MOISTURE_WINDOW_MINUTES = 180
MOISTURE_DEDUCT_FACTOR = 0.96
MOISTURE_DEDUCT_MIN_HUMIDITY = 92
MOISTURE_MIN_HUMIDITY = 85


class MoistureConflict(Exception):
    """409 冲突:payload 直接作为响应正文(必含 detail,另带 roomId / climateLogId / harvestId)。"""

    def __init__(self, payload: dict):
        super().__init__(str(payload.get("detail", "")))
        self.payload = payload


def matching_climate_log(db, room_id: int, harvested_at: datetime) -> Optional[ClimateLog]:
    """同室 recordedAt 不晚于 harvestedAt、间隔 <= 180 分钟的最近一条环境记录。"""
    window_start = harvested_at - timedelta(minutes=MOISTURE_WINDOW_MINUTES)
    return (
        db.query(ClimateLog)
        .filter(
            ClimateLog.room_id == room_id,
            ClimateLog.recorded_at <= harvested_at,
            ClimateLog.recorded_at >= window_start,
        )
        .order_by(ClimateLog.recorded_at.desc(), ClimateLog.id.desc())
        .first()
    )


def moisture_kg_for_harvest(db, harvest) -> float:
    """唯一扣水展示公式:返回该采收行的扣水后公斤 moisture_kg。

    weight_kg 永远保持称重原值,本函数只算展示值,不写回。
    """
    log = matching_climate_log(db, harvest.room_id, harvest.harvested_at)
    if log is None:
        raise MoistureConflict(
            {
                "detail": f"出菇室 {harvest.room_id} 在 180 分钟窗口内无环境记录,无法扣水",
                "roomId": harvest.room_id,
            }
        )
    if log.humidity_pct < MOISTURE_MIN_HUMIDITY:
        raise MoistureConflict(
            {
                "detail": f"环境记录 {log.id} 湿度 {log.humidity_pct}% 低于 85%,禁止扣水展示",
                "climateLogId": log.id,
            }
        )
    if log.humidity_pct >= MOISTURE_DEDUCT_MIN_HUMIDITY:
        return harvest.weight_kg * MOISTURE_DEDUCT_FACTOR
    return float(harvest.weight_kg)
