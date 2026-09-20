from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from marshmallow import ValidationError

from app.database import SessionLocal
from app import harvest_service
from app.harvest_service import HarvestConflict
from app.models.flush_harvest import FlushHarvest
from app.models.room import Room
from app.schemas.flush_harvest import (
    FlushHarvestCreateSchema,
    FlushHarvestOutSchema,
    FlushHarvestUpdateSchema,
)
from app.utils import validation_error_response

bp = Blueprint("flush_harvests", __name__, url_prefix="/api/flush-harvests")

create_schema = FlushHarvestCreateSchema()
update_schema = FlushHarvestUpdateSchema()
out_schema = FlushHarvestOutSchema()
out_many = FlushHarvestOutSchema(many=True)


def conflict_response(exc: HarvestConflict):
    return jsonify(exc.payload), exc.status_code


@bp.get("")
@jwt_required()
def list_flush_harvests():
    db = SessionLocal()
    try:
        room_id = request.args.get("roomId", type=int)
        q = db.query(FlushHarvest)
        if room_id is not None:
            q = q.filter(FlushHarvest.room_id == room_id)
        rows = q.order_by(FlushHarvest.harvested_at.desc()).all()
        # 无合格环境记录（找不到窗口记录 / 湿度过低）的采收行不得出现
        return jsonify(out_many.dump(harvest_service.dump_harvests(db, rows)))
    finally:
        db.close()


@bp.get("/<int:harvest_id>")
@jwt_required()
def get_flush_harvest(harvest_id: int):
    db = SessionLocal()
    try:
        item = db.query(FlushHarvest).filter(FlushHarvest.id == harvest_id).first()
        if not item:
            return jsonify({"detail": "采收记录不存在"}), 404
        try:
            return jsonify(out_schema.dump(harvest_service.dump_harvest(db, item)))
        except HarvestConflict as exc:
            return conflict_response(exc)
    finally:
        db.close()


@bp.post("")
@jwt_required()
def create_flush_harvest():
    db = SessionLocal()
    try:
        try:
            data = create_schema.load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return validation_error_response(err)
        room = db.query(Room).filter(Room.id == data["room_id"]).first()
        if not room:
            return jsonify({"detail": "出菇室不存在"}), 400
        item = FlushHarvest(
            room_id=data["room_id"],
            harvested_at=data["harvested_at"],
            flush_no=data["flush_no"],
            weight_kg=data["weight_kg"],
            grade=data["grade"],
            operator_name=data["operator_name"],
        )
        db.add(item)
        db.flush()
        try:
            payload = harvest_service.dump_harvest(db, item)
        except HarvestConflict as exc:
            # 校验不过：整行回滚，采收行不得出现
            db.rollback()
            return conflict_response(exc)
        db.commit()
        return jsonify(out_schema.dump(payload)), 201
    finally:
        db.close()


@bp.put("/<int:harvest_id>")
@jwt_required()
def update_flush_harvest(harvest_id: int):
    db = SessionLocal()
    try:
        item = db.query(FlushHarvest).filter(FlushHarvest.id == harvest_id).first()
        if not item:
            return jsonify({"detail": "采收记录不存在"}), 404
        try:
            data = update_schema.load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return validation_error_response(err)
        room = db.query(Room).filter(Room.id == data["room_id"]).first()
        if not room:
            return jsonify({"detail": "出菇室不存在"}), 400
        item.room_id = data["room_id"]
        item.harvested_at = data["harvested_at"]
        item.flush_no = data["flush_no"]
        # weightKg 保持称重原值：仅按入参更新原值，扣水永远由公式重算，绝不落库覆盖
        item.weight_kg = data["weight_kg"]
        item.grade = data["grade"]
        item.operator_name = data["operator_name"]
        db.flush()
        try:
            payload = harvest_service.dump_harvest(db, item)
        except HarvestConflict as exc:
            db.rollback()
            return conflict_response(exc)
        db.commit()
        return jsonify(out_schema.dump(payload))
    finally:
        db.close()


@bp.delete("/<int:harvest_id>")
@jwt_required()
def delete_flush_harvest(harvest_id: int):
    db = SessionLocal()
    try:
        item = db.query(FlushHarvest).filter(FlushHarvest.id == harvest_id).first()
        if not item:
            return jsonify({"detail": "采收记录不存在"}), 404
        db.delete(item)
        db.commit()
        return "", 204
    finally:
        db.close()
