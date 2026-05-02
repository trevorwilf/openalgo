"""Marshmallow schemas for v1 account endpoints (funds, orderbook,
tradebook, positionbook, holdings, orderstatus, openposition).

Phase 2 v4 (ADR 0023) — these schemas are India-specific by virtue of
their use sites (the v1 lane is hard-blocked for non-India brokers).
The ``LEGACY_INDIA_COMPATIBILITY = True`` sentinel marks the module so
the classifier and the v1-schema classification contract test
recognise it as legacy compatibility code.
"""

LEGACY_INDIA_COMPATIBILITY = True

from marshmallow import INCLUDE, Schema, fields, validate


class FundsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class OrderbookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class TradebookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class PositionbookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class HoldingsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class OrderStatusSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy = fields.Str(required=True)
    orderid = fields.Str(required=True)


class OpenPositionSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy = fields.Str(required=True)
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)
    product = fields.Str(required=True, validate=validate.OneOf(["MIS", "NRML", "CNC"]))


class AnalyzerSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class AnalyzerToggleSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    mode = fields.Bool(required=True)


class PingSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class ChartSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))

    class Meta:
        # Allow unknown fields - chart preferences can have any key-value pairs
        unknown = INCLUDE


class PnlSymbolsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
