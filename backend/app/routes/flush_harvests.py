from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from marshmallow import ValidationError

from app.database import SessionLocal
from app.models.flush_harvest import FlushHarvest
from app.models.room import Room
from app.moisture import MoistureConflict, moisture_kg_for_harvest
from app.schemas.flush_harvest import FlushHarvestCreateSchema, FlushHarvestOutSchema
from app.utils import validation_error_response

bp = Blueprint("flush_harvests", __name__, url_prefix="/api/flush-harvests")

create_schema = FlushHarvestCreateSchema()
out_schema = FlushHarvestOutSchema()


def _out(db, item: FlushHarvest) -> dict:
    """单条输出:weightKg 为称重原值,moistureKg 由唯一展示公式算出。"""
    data = out_schema.dump(item)
    data["moistureKg"] = moisture_kg_for_harvest(db, item)
    return data


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
        result = []
        for row in rows:
            try:
                result.append(_out(db, row))
            except MoistureConflict:
                continue  # 无法扣水的采收行不得出现
        return jsonify(result)
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
            return jsonify(_out(db, item))
        except MoistureConflict as err:
            return jsonify(err.payload), 409
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
        try:
            moisture_kg_for_harvest(db, item)
        except MoistureConflict as err:
            return jsonify(err.payload), 409  # 无法扣水,采收行不得出现(不落库)
        db.add(item)
        db.commit()
        db.refresh(item)
        return jsonify(_out(db, item)), 201
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
            data = create_schema.load(request.get_json(silent=True) or {})
        except ValidationError as err:
            return validation_error_response(err)
        room = db.query(Room).filter(Room.id == data["room_id"]).first()
        if not room:
            return jsonify({"detail": "出菇室不存在"}), 400
        item.room_id = data["room_id"]
        item.harvested_at = data["harvested_at"]
        item.flush_no = data["flush_no"]
        item.weight_kg = data["weight_kg"]
        item.grade = data["grade"]
        item.operator_name = data["operator_name"]
        try:
            moisture_kg_for_harvest(db, item)  # 改采收时重算
        except MoistureConflict as err:
            db.rollback()  # 整单回滚,保留原值
            return jsonify(err.payload), 409
        db.commit()
        return jsonify(_out(db, item))
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
