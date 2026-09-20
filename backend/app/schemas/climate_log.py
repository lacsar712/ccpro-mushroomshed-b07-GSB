from marshmallow import Schema, fields, validate


class ClimateLogCreateSchema(Schema):
    room_id = fields.Int(required=True, data_key="roomId")
    recorded_at = fields.DateTime(required=True, data_key="recordedAt")
    temp_c = fields.Float(required=True, data_key="tempC")
    humidity_pct = fields.Int(
        required=True,
        data_key="humidityPct",
        validate=validate.Range(min=1, max=100, error="humidityPct 须在 1–100 之间"),
    )
    co2_ppm = fields.Float(allow_none=True, data_key="co2Ppm")
    notes = fields.Str(allow_none=True)


# 改环境记录与新增字段一致：改 recordedAt 后会重新校验 180 分钟窗口内的潮次
class ClimateLogUpdateSchema(ClimateLogCreateSchema):
    pass


class ClimateLogOutSchema(Schema):
    id = fields.Int(dump_only=True)
    room_id = fields.Int(data_key="roomId")
    recorded_at = fields.DateTime(data_key="recordedAt")
    temp_c = fields.Float(data_key="tempC")
    humidity_pct = fields.Int(data_key="humidityPct")
    co2_ppm = fields.Float(allow_none=True, data_key="co2Ppm")
    notes = fields.Str(allow_none=True)
