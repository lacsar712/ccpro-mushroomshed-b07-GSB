from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from app.database import SessionLocal
from app.models.climate_log import ClimateLog
from app.models.flush_harvest import FlushHarvest
from app.models.room import Room
from app.models.shed import Shed
from app.moisture import MoistureConflict, moisture_kg_for_harvest
from app.schemas.dashboard import DashboardStatsSchema

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")

stats_schema = DashboardStatsSchema()


@bp.get("/stats")
@jwt_required()
def get_stats():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        shed_total = db.query(func.count(Shed.id)).scalar() or 0
        fruiting_room_count = (
            db.query(func.count(Room.id)).filter(Room.status == "fruiting").scalar() or 0
        )
        climate_last_24h = (
            db.query(func.count(ClimateLog.id))
            .filter(ClimateLog.recorded_at >= now - timedelta(hours=24))
            .scalar()
            or 0
        )
        # 近 7 日扣水后公斤:与采收列表/单条共用同一展示公式,无法扣水的行不计入
        recent_harvests = (
            db.query(FlushHarvest)
            .filter(FlushHarvest.harvested_at >= now - timedelta(days=7))
            .all()
        )
        harvest_kg_last_7d = 0.0
        for h in recent_harvests:
            try:
                harvest_kg_last_7d += moisture_kg_for_harvest(db, h)
            except MoistureConflict:
                continue
        payload = {
            "shed_total": shed_total,
            "fruiting_room_count": fruiting_room_count,
            "climate_last_24h": climate_last_24h,
            "harvest_kg_last_7d": float(harvest_kg_last_7d),
        }
        return jsonify(stats_schema.dump(payload))
    finally:
        db.close()
