from drf_spectacular.utils import OpenApiExample

MY_ORDERS_RESPONSE = OpenApiExample(
    name="order response",
    response_only=True,
    value=[
        {
            "id": 0,
            "state": "new",
            "dt": "2022-09-23T05:46:37.532422Z",
            "total_sum": 0,
            "address": {
                "id": 0,
                "city": "string",
                "street": "string",
                "house": "string",
                "structure": "string",
                "building": "string",
                "apartment": "string",
            },
            "shops": [
                {
                    "id": 0,
                    "name": "string",
                    "shop_sum": 0,
                    "ordered_items": [
                        {
                            "id": 0,
                            "quantity": 0,
                            "product_info": {
                                "id": 0,
                                "external_id": 0,
                                "model": "string",
                                "product": {"name": "string", "category": "string"},
                                "product_parameters": [
                                    {"parameter": "string", "value": "string"},
                                ],
                                "price": 0,
                                "price_rrc": 0,
                            },
                        }
                    ],
                    "delivery": 0,
                }
            ],
            "total_delivery": 0,
        }
    ],
)

BASKET_RESPONSE = OpenApiExample(
    name="basket response",
    response_only=True,
    value=[
        {
            "id": 0,
            "state": "basket",
            "dt": "2022-09-23T05:46:37.532422Z",
            "total_sum": 0,
            "address": None,
            "shops": [
                {
                    "id": 0,
                    "name": "string",
                    "shop_sum": 0,
                    "ordered_items": [
                        {
                            "id": 0,
                            "quantity": 0,
                            "product_info": {
                                "id": 0,
                                "external_id": 0,
                                "model": "string",
                                "product": {"name": "string", "category": "string"},
                                "product_parameters": [
                                    {"parameter": "string", "value": "string"},
                                ],
                                "price": 0,
                                "price_rrc": 0,
                            },
                        }
                    ],
                    "delivery": 0,
                }
            ],
            "total_delivery": 0,
        }
    ],
)

PARTNER_ORDERS_RESPONSE = OpenApiExample(
    name="order response",
    response_only=True,
    value=[
        {
            "id": 0,
            "state": "new",
            "dt": "2022-09-23T05:46:37.532422Z",
            "total_sum": 0,
            "address": {
                "id": 0,
                "city": "string",
                "street": "string",
                "house": "string",
                "structure": "string",
                "building": "string",
                "apartment": "string",
            },
            "ordered_items": [
                {
                    "id": 0,
                    "quantity": 0,
                    "product_info": {
                        "id": 0,
                        "external_id": 0,
                        "model": "string",
                        "product": {"name": "string", "category": "string"},
                        "product_parameters": [
                            {"parameter": "string", "value": "string"},
                        ],
                        "price": 0,
                        "price_rrc": 0,
                    },
                }
            ],
        }
    ],
)
