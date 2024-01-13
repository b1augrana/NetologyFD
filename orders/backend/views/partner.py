import datetime
from distutils.util import strtobool

from backend.models import ConfirmEmailToken, Delivery, Order, Shop, User
from backend.permissions import IsShop
from backend.serializers import (
    DeliverySerializer,
    PartnerOrderSerializer,
    PartnerSerializer,
    ShopSerializer,
    StatusFalseSerializer,
    StatusTrueSerializer,
    UserWithPasswordSerializer,
)
from backend.tasks import send_email_task
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import F, Sum
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import fields, parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from silk.profiling.profiler import silk_profile

from orders.schema import PARTNER_ORDERS_RESPONSE


class PartnerViewSet(viewsets.GenericViewSet):
    """
    Viewset for partners
    """

    queryset = User.objects.filter(type="shop")
    serializer_class = PartnerSerializer
    permission_classes = [IsAuthenticated, IsShop]

    @extend_schema(
        request=UserWithPasswordSerializer,
        responses={201: StatusTrueSerializer, 400: StatusFalseSerializer},
    )
    @action(methods=["post"], detail=False, permission_classes=[])
    def register(self, request):
        """
        Partner registry.
        Send email to admin about registration, admin have to acivate new partner
        """

        # check args
        if not {"email", "password", "company"}.issubset(request.data):
            return JsonResponse(
                {"Status": False, "Errors": "Не указаны все необходимые аргументы"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # check password
        try:
            validate_password(request.data["password"])
        except Exception as password_error:
            return JsonResponse(
                {"Status": False, "Errors": {"password": str(password_error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        else:
            # check data
            partner_serializer = self.get_serializer(data=request.data)
            if partner_serializer.is_valid():
                # save partner
                user = partner_serializer.save()
                user.set_password(request.data["password"])
                user.save()

                # email verification
                token, _ = ConfirmEmailToken.objects.get_or_create(user_id=user.id)
                title = f"Password Reset Token for {token.user.email}"
                message = token.key
                addressee_list = [token.user.email]
                send_email_task.delay(title, message, addressee_list)

                # email to admin
                title = f"Новый поставщик: {user}"
                message = (
                    f"Зарегистрировался новый поставщик: {user}. "
                    f"Для начала работы необходимо его активировать."
                )
                addressee_list = [settings.ADMIN_EMAIL]
                send_email_task.delay(title, message, addressee_list)

                return JsonResponse({"Status": True}, status=status.HTTP_201_CREATED)
            else:
                return JsonResponse(
                    {"Status": False, "Errors": partner_serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

    @extend_schema(
        request=inline_serializer(
            "PriceInfoUploadSerializer",
            {
                "url": fields.URLField(required=False),
                "file": fields.FileField(required=False),
            },
        ),
        responses={200: StatusTrueSerializer, 400: StatusFalseSerializer},
    )
    @action(
        methods=["post"],
        detail=False,
        url_path="update",
        parser_classes=[parsers.MultiPartParser],
    )
    def price_info(self, request):
        """
        Load file or url of pricelist to update
        """

        data = {
            "file": None,
            "url": None,
            "update_dt": datetime.date.today(),
            "is_uptodate": False,
        }
        file = request.FILES.get("file")
        url = request.data.get("url")
        if file:
            data["file"] = file
        elif url:
            validate_url = URLValidator()
            try:
                validate_url(url)
            except ValidationError as e:
                return JsonResponse(
                    {"Status": False, "Error": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            data["url"] = url
        else:
            return JsonResponse(
                {"Status": False, "Error": "Необходим либо файл, либо ссылка."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        shop, created = Shop.objects.get_or_create(user_id=request.user.id)
        if created:
            data["name"] = f"- Актуализируйте прайс-лист -"
        shop_serializer = ShopSerializer(shop, data=data, partial=True)
        if shop_serializer.is_valid():
            shop_serializer.save()

            # send email to admin about new pricelist
            title = f"{shop_serializer.data['name']}: обновление прайса"
            message = (
                f"Пользователь {request.user} сообщил о новом "
                f"прайс-листе магазина {shop_serializer.data['name']}"
            )
            addressee_list = [settings.ADMIN_EMAIL]
            send_email_task.delay(title, message, addressee_list)

            return JsonResponse({"Status": True})
        else:
            return JsonResponse(
                {"Status": False, "Errors": shop_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @extend_schema(
        methods=["get"],
        responses=ShopSerializer,
        description="Получение статуса поставщика",
    )
    @extend_schema(
        methods=["post"],
        description="Изменение статуса поставщика",
        request=inline_serializer(
            "ChangeShopStateSerializer", {"state": fields.BooleanField()}
        ),
        responses={200: ShopSerializer, 400: StatusFalseSerializer},
    )
    @action(methods=["get", "post"], detail=False)
    def state(self, request):
        """
        GET or POST partner status
        """

        if request.method == "GET":
            try:
                shop = request.user.shop
            except Exception as e:
                return JsonResponse(
                    {"Status": False, "Error": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                serializer = ShopSerializer(shop)
                return Response(serializer.data)

        else:
            state = request.data.get("state")
            if not state:
                return JsonResponse(
                    {"Status": False, "Errors": "Не указаны все необходимые аргументы"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                Shop.objects.filter(user_id=request.user.id).update(
                    state=strtobool(state)
                )
                return JsonResponse({"Status": True})
            except ValueError as error:
                return JsonResponse(
                    {"Status": False, "Errors": str(error)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

    @silk_profile(name="Orders")
    @extend_schema(examples=[PARTNER_ORDERS_RESPONSE])
    @action(detail=False)
    def orders(self, request):
        """
        GET partner order
        """

        order = (
            Order.objects.filter(
                ordered_items__product_info__shop__user_id=request.user.id
            )
            .exclude(state="basket")
            .prefetch_related(
                "ordered_items__product_info__shop",
                "ordered_items__product_info__product__category",
                "ordered_items__product_info__product_parameters__parameter",
            )
            .select_related("user")
            .annotate(
                total_sum=Sum(
                    F("ordered_items__quantity")
                    * F("ordered_items__product_info__price")
                )
            )
            .distinct()
        )

        serializer = PartnerOrderSerializer(
            order, partner_id=request.user.id, many=True
        )
        return Response(serializer.data)

    @extend_schema(
        methods=["get"],
        description="Получение стоимости доставки",
        responses=DeliverySerializer(many=True),
    )
    @extend_schema(
        methods=["post"],
        description="Добавление или изменение стоимости доставки "
        "для указанной минимальной суммы.",
        request=inline_serializer(
            "UpdateDeliverySerializer",
            {"delivery": fields.ListField(child=DeliverySerializer())},
        ),
        responses={200: DeliverySerializer(many=True), 400: StatusFalseSerializer},
    )
    @action(methods=["get", "post"], detail=False)
    def delivery(self, request):
        """
        GET or POST delivery cost
        """

        if request.method == "GET":
            delivery = Delivery.objects.filter(shop=request.user.shop).order_by(
                "min_sum"
            )
            serializer = DeliverySerializer(delivery, many=True)
            return Response(serializer.data)
        else:
            delivery = request.data.get("delivery")
            if not delivery:
                return JsonResponse(
                    {"Status": False, "Errors": "Не указаны все необходимые аргументы"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            for item in delivery:
                delivery_obj = Delivery.objects.filter(
                    shop=request.user.shop, min_sum=item["min_sum"]
                ).first()
                if delivery_obj:
                    delivery_serializer = DeliverySerializer(
                        delivery_obj, data={"cost": item["cost"]}, partial=True
                    )
                else:
                    data = {"shop": request.user.shop.id, **item}
                    delivery_serializer = DeliverySerializer(data=data)

                if delivery_serializer.is_valid():
                    delivery_serializer.save()
                    return JsonResponse({"Status": True})
                else:
                    return JsonResponse(
                        {"Status": False, "Errors": delivery_serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
