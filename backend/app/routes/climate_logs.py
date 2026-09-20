from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from marshmallow import ValidationError

from app.database import SessionLocal
from app import harvest_service
from app.harvest_service import HarvestConflict
from app.models.climate_log import ClimateLog
from app.models.flush_harvest import FlushHarvest
from app.models.room import Room
from app.schemas.climate_log import (
    ClimateLogCreateSchema,
    ClimateLogOutSchema,
    ClimateLogUpdateSchema,
)
from app.utils import validation_error_response

bp = Blueprint("climate_logs", __name__, url_prefix="/api/climate-logs")

create_schema = ClimateLogCreateSchema()
update_schema = ClimateLogUpdateSchema()
out_schema = ClimateLogOutSchema()
out_many = ClimateLogOutSchema(many=True)


def attached_harvest_ids(db, log: ClimateLog) -> list[int]:
    """当前挂在该环境记录上的潮次：同室采收里最近窗口记录正是本条。"""

    harvests = db.query(FlushHarvest).filter(FlushHarvest.room_id == log.room_id).all()
    ids = []
    for harvest in harvests:
        ref = harvest_service.find_reference_climate_log(db, harvest)
        if ref is not None and ref.id == log.id:
            ids.append(harvest.id)
    return ids


@bp.get("")
@jwt_required()
def list_climate_logs():
    db = SessionLocal()
    try:
        room_id = request.args.get("roomId", type=int)
        q = db.query(ClimateLog)
        if room_id is not None:
            q = q.filter(ClimateLog.room_id == room_id)
        rows = q.order_by(ClimateLog.recorded_at.desc()).all()
        return jsonify(out_many.dump(rows))
    finally:
        db.close()


@bp.post("")
@jwt_required()
def create_climate_log():
    db = SessionLocal()
    try:
        try:
            data = create_schema.load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return validation_error_response(err)
        room = db.query(Room).filter(Room.id == data["room_id"]).first()
        if not room:
            return jsonify({"detail": "出菇室不存在"}), 400
        item = ClimateLog(
            room_id=data["room_id"],
            recorded_at=data["recorded_at"],
            temp_c=data["temp_c"],
            humidity_pct=data["humidity_pct"],
            co2_ppm=data.get("co2_ppm"),
            notes=data.get("notes"),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return jsonify(out_schema.dump(item)), 201
    finally:
        db.close()


@bp.put("/<int:log_id>")
@jwt_required()
def update_climate_log(log_id: int):
    db = SessionLocal()
    try:
        item = db.query(ClimateLog).filter(ClimateLog.id == log_id).first()
        if not item:
            return jsonify({"detail": "环境记录不存在"}), 404
        try:
            data = update_schema.load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return validation_error_response(err)
        room = db.query(Room).filter(Room.id == data["room_id"]).first()
        if not room:
            return jsonify({"detail": "出菇室不存在"}), 400

        # 改动前先记下挂在本条上的潮次，改完（时刻/湿度等）逐条按同一公式重算
        linked_ids = attached_harvest_ids(db, item)

        item.room_id = data["room_id"]
        item.recorded_at = data["recorded_at"]
        item.temp_c = data["temp_c"]
        item.humidity_pct = data["humidity_pct"]
        item.co2_ppm = data.get("co2_ppm")
        item.notes = data.get("notes")
        db.flush()

        broken_ids: list[int] = []
        for harvest_id in linked_ids:
            harvest = db.query(FlushHarvest).filter(FlushHarvest.id == harvest_id).first()
            if harvest is None:
                continue
            try:
                harvest_service.dump_harvest(db, harvest)
            except HarvestConflict:
                # 被挤出 180 分钟窗口，或新湿度低于 85
                broken_ids.append(harvest_id)

        if broken_ids:
            # 整单回滚，环境记录改动不落库
            db.rollback()
            return (
                jsonify(
                    {
                        "detail": f"环境记录改动会使 {len(broken_ids)} 条潮次失去 180 分钟内合格环境记录",
                        "harvestIds": broken_ids,
                    }
                ),
                409,
            )

        db.commit()
        db.refresh(item)
        return jsonify(out_schema.dump(item))
    finally:
        db.close()


@bp.delete("/<int:log_id>")
@jwt_required()
def delete_climate_log(log_id: int):
    db = SessionLocal()
    try:
        item = db.query(ClimateLog).filter(ClimateLog.id == log_id).first()
        if not item:
            return jsonify({"detail": "环境记录不存在"}), 404
        db.delete(item)
        db.commit()
        return "", 204
    finally:
        db.close()
