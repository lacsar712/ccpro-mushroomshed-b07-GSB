from marshmallow import Schema, fields


class DashboardStatsSchema(Schema):
    shed_total = fields.Int(data_key="shedTotal")
    fruiting_room_count = fields.Int(data_key="fruitingRoomCount")
    climate_last_24h = fields.Int(data_key="climateLast24h")
    # 七日公斤为扣水公斤（moistureKg），与采收列表/单条同一公式
    moisture_kg_last_7d = fields.Float(data_key="moistureKgLast7d")
