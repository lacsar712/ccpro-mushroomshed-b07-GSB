from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from marshmallow import ValidationError

from app.database import SessionLocal
from app.models.climate_log import ClimateLog
from app.models.flush_harvest import FlushHarvest
from app.models.room import Room
from app.moisture import matching_climate_log
from app.schemas.climate_log import ClimateLogCreateSchema, ClimateLogOutSchema
from app.utils import validation_error_response

bp = Blueprint("climate_logs", __name__, url_prefix="/api/climate-logs")

create_schema = ClimateLogCreateSchema()
out_schema = ClimateLogOutSchema()
out_many = ClimateLogOutSchema(many=True)


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
            data = create_schema.load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return validation_error_response(err)
        room = db.query(Room).filter(Room.id == data["room_id"]).first()
        if not room:
            return jsonify({"detail": "出菇室不存在"}), 400
        # 变更前已挂在该环境记录上的潮次(当前匹配到本记录的采收)
        linked = []
        candidates = db.query(FlushHarvest).filter(FlushHarvest.room_id == item.room_id).all()
        for h in candidates:
            m = matching_climate_log(db, h.room_id, h.harvested_at)
            if m is not None and m.id == item.id:
                linked.append(h)
        item.room_id = data["room_id"]
        item.recorded_at = data["recorded_at"]
        item.temp_c = data["temp_c"]
        item.humidity_pct = data["humidity_pct"]
        item.co2_ppm = data.get("co2_ppm")
        item.notes = data.get("notes")
        db.flush()  # autoflush=False,显式刷入让后续查询看到新时刻
        pushed_out = sorted(
            h.id for h in linked if matching_climate_log(db, h.room_id, h.harvested_at) is None
        )
        if pushed_out:
            db.rollback()  # 把已挂潮次挤出 180 分钟窗口:整单回滚
            return (
                jsonify(
                    {
                        "detail": f"变更将把采收 {pushed_out} 挤出 180 分钟窗口,已整单回滚",
                        "harvestId": pushed_out,
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
