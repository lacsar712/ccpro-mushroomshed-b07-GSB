"""采收扣水（moistureKg）统一计算。

唯一公式入口：采收列表、采收单条、Dashboard 七日公斤三处都只能调用本模块，
不得各自再实现一套。

规则
----
取同室 recordedAt 不晚于 harvestedAt 且间隔不超过 ``MOISTURE_WINDOW_MINUTES``
分钟的最近一条 ClimateLog：

* 找不到环境记录 → ``NoClimateLogError``（HTTP 409，正文带 roomId）
* humidity_pct >= 92 → moistureKg = weightKg * 0.96
* 85 <= humidity_pct < 92 → moistureKg = weightKg（不扣水）
* humidity_pct < 85 → ``LowHumidityError``（HTTP 409，正文带 climateLogId）

库存 weightKg 始终保持称重原值，本模块不写库、不覆盖。
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.climate_log import ClimateLog
from app.models.flush_harvest import FlushHarvest

# 湿度达到该值开始扣水（含）
MOISTURE_THRESHOLD_HIGH = 92
# 湿度低于该值拒绝采收
MOISTURE_THRESHOLD_LOW = 85
# 扣水系数
MOISTURE_FACTOR = 0.96
# 采收时刻向前匹配环境记录的窗口（分钟）
MOISTURE_WINDOW_MINUTES = 180


class HarvestConflict(Exception):
    """采收与环境记录无法匹配，序列化为 HTTP 409。"""

    status_code = 409


class NoClimateLogError(HarvestConflict):
    def __init__(self, room_id: int):
        self.room_id = room_id
        super().__init__(f"采收前 {MOISTURE_WINDOW_MINUTES} 分钟内无环境记录")

    @property
    def payload(self) -> dict:
        return {"detail": str(self), "roomId": self.room_id}


class LowHumidityError(HarvestConflict):
    def __init__(self, climate_log_id: int, humidity_pct: int):
        self.climate_log_id = climate_log_id
        self.humidity_pct = humidity_pct
        super().__init__(f"环境记录湿度 {humidity_pct}% 低于 {MOISTURE_THRESHOLD_LOW}%，不可采收")

    @property
    def payload(self) -> dict:
        return {"detail": str(self), "climateLogId": self.climate_log_id}


def find_reference_climate_log(db: Session, harvest: FlushHarvest) -> ClimateLog | None:
    """同室 recordedAt 不晚于 harvestedAt 且间隔不超过 180 分钟的最近一条。"""

    window_start = harvest.harvested_at - timedelta(minutes=MOISTURE_WINDOW_MINUTES)
    return (
        db.query(ClimateLog)
        .filter(
            ClimateLog.room_id == harvest.room_id,
            ClimateLog.recorded_at <= harvest.harvested_at,
            ClimateLog.recorded_at >= window_start,
        )
        .order_by(ClimateLog.recorded_at.desc())
        .first()
    )


def moisture_kg(weight_kg: float, humidity_pct: int) -> float:
    """纯扣水公式：>=92 乘 0.96；85..91（含 85、不含 92）为原值。"""

    if humidity_pct >= MOISTURE_THRESHOLD_HIGH:
        return weight_kg * MOISTURE_FACTOR
    return weight_kg


def evaluate_harvest(db: Session, harvest: FlushHarvest) -> dict:
    """对单条采收求值，返回带 moistureKg 的 dict；不满足规则抛 409 异常。"""

    log = find_reference_climate_log(db, harvest)
    if log is None:
        raise NoClimateLogError(harvest.room_id)
    if log.humidity_pct < MOISTURE_THRESHOLD_LOW:
        raise LowHumidityError(log.id, log.humidity_pct)
    return {
        "id": harvest.id,
        "room_id": harvest.room_id,
        "harvested_at": harvest.harvested_at,
        "flush_no": harvest.flush_no,
        "weight_kg": harvest.weight_kg,
        "moisture_kg": moisture_kg(harvest.weight_kg, log.humidity_pct),
        "grade": harvest.grade,
        "operator_name": harvest.operator_name,
    }


def dump_harvest(db: Session, harvest: FlushHarvest) -> dict:
    """单条求值；不合格直接抛 409（采收单条、创建、修改共用）。"""

    return evaluate_harvest(db, harvest)


def dump_harvests(db: Session, harvests: list[FlushHarvest]) -> list[dict]:
    """列表求值：无合格环境记录的采收行不得出现，直接剔除（仍逐条调用同一公式）。"""

    rows: list[dict] = []
    for harvest in harvests:
        try:
            rows.append(evaluate_harvest(db, harvest))
        except HarvestConflict:
            continue
    return rows


def moisture_kg_sum(db: Session, harvests: list[FlushHarvest]) -> float:
    """Dashboard 七日公斤：服务端按同一公式对有效采收行求和。"""

    return float(sum(item["moisture_kg"] for item in dump_harvests(db, harvests)))
