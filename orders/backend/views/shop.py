from backend.models import Category, Delivery, Order, OrderItem, ProductInfo, Shop
from backend.serializers import (
    CategorySerializer,
    OrderItemSerializer,
    OrderSerializer,
    ProductInfoSerializer,
    ShopOrderSerializer,
    ShopSerializer,
    StatusFalseSerializer,
    StatusTrueSerializer,
)
from backend.tasks import send_email_task
from django.conf import settings
from django.db import IntegrityError
from django.db.models import F, Q, Sum
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import fields, status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from silk.profiling.profiler import silk_profile

from orders.schema import BASKET_RESPONSE, MY_ORDERS_RESPONSE


class CategoryView(ListAPIView):
    """
    Category list
    """

    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ShopView(ListAPIView):
    """
    Shop list
    """

    queryset = Shop.objects.filter(state=True)
    serializer_class = ShopSerializer


class ProductInfoView(APIView):
    """
    Product filter
    """

    queryset = ProductInfo.objects.none()
    serializer_class = ProductInfoSerializer

    @silk_profile(name="View Product Info")
    def get(self, request, *args, **kwargs):
        query = Q(shop__state=True)
        shop_id = request.query_params.get("shop_id")
        category_id = request.query_params.get("category_id")

        if shop_id:
            query = query & Q(shop_id=shop_id)

        if category_id:
            query = query & Q(product__category_id=category_id)

        # фильтруем и отбрасываем дубликаты
        queryset = (
            ProductInfo.objects.filter(query)
            .select_related("shop", "product__category")
            .prefetch_related("product_parameters__parameter")
            .distinct()
        )

        serializer = ProductInfoSerializer(queryset, many=True)

        return Response(serializer.data)


class BasketView(APIView):
    """
    User basket
    """

    queryset = Order.objects.none()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(examples=[BASKET_RESPONSE])
    def get(self, request, *args, **kwargs):
        """
        GET Basket
        """

        basket = (
            Order.objects.filter(user_id=request.user.id, state="basket")
            .prefetch_related(
                "ordered_items__product_info__shop",
                "ordered_items__product_info__product__category",
                "ordered_items__product_info__product_parameters__parameter",
            )
            .annotate(
                total_sum=Sum(
                    F("ordered_items__quantity")
                    * F("ordered_items__product_info__price")
                )
            )
            .distinct()
        )

        serializer = OrderSerializer(basket, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=inline_serializer(
            "BasketAddRequestSerializer",
            {"items": fields.ListField(child=OrderItemSerializer())},
        ),
        responses={
            200: inline_serializer(
                "BasketAddResponseSerializer",
                {
                    "Status": fields.BooleanField(),
                    "Создано объектов": fields.IntegerField(),
                },
            ),
            400: StatusFalseSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        """
        Add products in Basket
        """

        items_list = request.data.get("items")
        if not items_list:
            return JsonResponse(
                {"Status": False, "Errors": "Не указаны все необходимые аргументы"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        basket, _ = Order.objects.get_or_create(user_id=request.user.id, state="basket")
        objects_created = 0
        for order_item in items_list:
            order_item.update({"order": basket.id})
            serializer = OrderItemSerializer(data=order_item)
            if serializer.is_valid():
                try:
                    serializer.save()
                except IntegrityError as error:
                    return JsonResponse(
                        {"Status": False, "Errors": str(error)},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                else:
                    objects_created += 1
            else:
                return JsonResponse(
                    {"Status": False, "Errors": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return JsonResponse({"Status": True, "Создано объектов": objects_created})

    @extend_schema(
        request=inline_serializer(
            "BasketUpdateRequestSerializer",
            {
                "items": fields.ListField(
                    child=inline_serializer(
                        "BasketItemUpdateRequestSerializer",
                        {
                            "id": fields.IntegerField(),
                            "quantity": fields.IntegerField(),
                        },
                    )
                )
            },
        ),
        responses={
            200: inline_serializer(
                "BasketUpdateResponseSerializer",
                {
                    "Status": fields.BooleanField(),
                    "Обновлено объектов": fields.IntegerField(),
                    "Удалено объектов": fields.IntegerField(),
                },
            ),
            400: StatusFalseSerializer,
        },
    )
    def put(self, request, *args, **kwargs):
        """
        Change quantity of products in basket, if 0 delete position
        """

        items_list = request.data.get("items")
        if not items_list:
            return JsonResponse(
                {"Status": False, "Errors": "Не указаны все необходимые аргументы"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            basket = Order.objects.get(user_id=request.user.id, state="basket")
        except Order.DoesNotExist:
            return JsonResponse(
                {"Status": False, "Errors": "Нет заказа со статусом корзины"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        objects_updated, deleted_count = 0, 0
        query = Q()
        has_objects_to_delete = False

        for order_item in items_list:
            item_id, qty = order_item.get("id"), order_item.get("quantity")

            if type(item_id) == int and type(qty) == int:
                if qty == 0:
                    query = query | Q(order_id=basket.id, id=item_id)
                    has_objects_to_delete = True
                else:
                    objects_updated += OrderItem.objects.filter(
                        order_id=basket.id, id=item_id
                    ).update(quantity=qty)

        if has_objects_to_delete:
            deleted_count, _ = OrderItem.objects.filter(query).delete()

        if objects_updated or deleted_count:
            return JsonResponse(
                {
                    "Status": True,
                    "Обновлено объектов": objects_updated,
                    "Удалено объектов": deleted_count,
                }
            )
        else:
            return JsonResponse(
                {"Status": False, "Errors": "Нет таких позиций в корзине"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class OrderView(APIView):
    """
    GET and POST user orders
    """

    queryset = Order.objects.none()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(examples=[MY_ORDERS_RESPONSE])
    def get(self, request, *args, **kwargs):
        """
        GET my orders
        """

        order = (
            Order.objects.filter(user_id=request.user.id)
            .exclude(state="basket")
            .prefetch_related(
                "ordered_items__product_info__shop",
                "ordered_items__product_info__product__category",
                "ordered_items__product_info__product_parameters__parameter",
            )
            .select_related("address")
            .annotate(
                total_sum=Sum(
                    F("ordered_items__quantity")
                    * F("ordered_items__product_info__price")
                )
            )
            .distinct()
        )

        serializer = OrderSerializer(order, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=inline_serializer(
            "OrderFromBasketRequestSerializer", {"address_id": fields.IntegerField()}
        ),
        responses={200: StatusTrueSerializer, 400: StatusFalseSerializer},
    )
    def post(self, request, *args, **kwargs):
        """
        POST order from basket
        send new order mail to admin
        send order status to user
        """

        try:
            basket = Order.objects.get(user_id=request.user.id, state="basket")
        except Order.DoesNotExist:
            return JsonResponse(
                {"Status": False, "Errors": "Нет заказа со статусом корзины"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invalid_deliveries = []
        shops = (
            Shop.objects.filter(product_infos__ordered_items__order=basket.id)
            .prefetch_related(
                "product_infos__product__category",
                "product_infos__product_parameters__parameter",
            )
            .annotate(
                shop_sum=Sum(
                    F("product_infos__ordered_items__quantity")
                    * F("product_infos__price")
                )
            )
            .distinct()
        )
        for shop in shops:
            shop_data = ShopOrderSerializer(shop, order_id=basket.id).data
            shop_deliveries = Delivery.objects.filter(shop=shop)
            if not shop_deliveries:
                invalid_deliveries.append(
                    f"{shop_data['name']}: " f"стоимость доставки недоступна."
                )
            else:
                shop_delivery = (
                    shop_deliveries.filter(min_sum__lte=shop_data["shop_sum"])
                    .order_by("-min_sum")
                    .first()
                )
                if shop_delivery is None:
                    invalid_deliveries.append(
                        f"{shop_data['name']}: сумма заказа меньше минимальной"
                    )
        if invalid_deliveries:
            return JsonResponse(
                {"Status": False, "Errors": invalid_deliveries},
                status=status.HTTP_400_BAD_REQUEST,
            )

        address_id = request.data.get("address_id")
        if not address_id:
            return JsonResponse(
                {"Status": False, "Errors": "Не указаны все необходимые аргументы"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if type(address_id) != int:
            return JsonResponse(
                {"Status": False, "Errors": "Неправильно указаны аргументы"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            basket.address_id = address_id
            basket.state = "new"
            basket.save()
        except IntegrityError:
            return JsonResponse(
                {"Status": False, "Errors": "Адрес не найден"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        else:
            # send order status email to user
            title = f"Обновление статуса заказа {basket.id}"
            message = f"Заказ {basket.id} получил статус Новый."
            addressee_list = [basket.user.email]
            send_email_task.delay(title, message, addressee_list)

            # send new order emeail to admin
            title = f"Новый заказ от {basket.user}"
            message = (
                f"Пользователем {basket.user} оформлен " f"новый заказ {basket.id}."
            )
            addressee_list = [settings.ADMIN_EMAIL]
            send_email_task.delay(title, message, addressee_list)

            return JsonResponse({"Status": True})
