from datetime import timedelta
import csv
import json
import importlib
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group, User
from django.db.models import Count, F, Max, Q, Sum
from django.db import transaction
from django.db.models.functions import TruncMonth
from django.http import Http404, HttpResponse, JsonResponse
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    CategoryForm,
    CompanyProfileForm,
    DeliveryNoteForm,
    DeliveryNoteItemFormSet,
    DriverForm,
    EquipmentForm,
    FleetFuelLogForm,
    FleetMaintenanceForm,
    GoodsReceiptForm,
    GoodsReceiptItemFormSet,
    GoodsIssueForm,
    GoodsIssueItemFormSet,
    GoodsReturnForm,
    GoodsReturnItemFormSet,
    PPEIssueForm,
    PPEIssueItemFormSet,
    WarehouseTransferPresetForm,
    WarehouseProjectLinkForm,
    UserStoreScopeForm,
    ProjectRequisitionForm,
    WorkspaceRequisitionForm,
    RequisitionItemFormSet,
    InventoryBalanceForm,
    InventoryMovementForm,
    InventoryMovementHeaderForm,
    MovementItemFormSet,
    MaterialForm,
    MaterialReturnForm,
    MobileEquipmentForm,
    ProjectForm,
    WarehouseForm,
    RequisitionForm,
    StoreLocationForm,
    StorageBinForm,
    StockTransactionForm,
    SubCategoryForm,
)
from .models import (
    Category,
    AuditLog,
    CompanyProfile,
    DEPARTMENTS,
    DeliveryNote,
    DeliveryNoteItem,
    Driver,
    Equipment,
    FleetFuelLog,
    FleetMaintenance,
    GoodsReceipt,
    GoodsReceiptItem,
    GoodsIssue,
    GoodsIssueItem,
    GoodsReturn,
    GoodsReturnItem,
    PPEIssue,
    PPEIssueItem,
    InventoryBalance,
    InventoryMovement,
    Material,
    MaterialReturn,
    MobileEquipment,
    Project,
    Requisition,
    RequisitionItem,
    RequisitionReadReceipt,
    RequisitionReservation,
    Warehouse,
    StoreLocation,
    StorageBin,
    StockTransaction,
    SubCategory,
    UserStoreScope,
)

try:
    from openpyxl import Workbook
except Exception:
    Workbook = None


def _load_reportlab_modules():
    try:
        pagesizes = importlib.import_module("reportlab.lib.pagesizes")
        units = importlib.import_module("reportlab.lib.units")
        utils = importlib.import_module("reportlab.lib.utils")
        pdfgen_canvas = importlib.import_module("reportlab.pdfgen.canvas")
        return pagesizes.A4, units.mm, utils.ImageReader, pdfgen_canvas
    except Exception:
        return None


def login_view(request):
    if request.user.is_authenticated:
        return redirect("workspace_home")

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        next_url = request.GET.get("next") or "workspace_home"
        return redirect(next_url)

    return render(request, "SupplChain_MNG/login.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("login")


def _period_start(period):
    now = timezone.now()
    mapping = {
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
        "365d": now - timedelta(days=365),
    }
    return mapping.get(period)


def _collect_filters(request):
    return {
        "name": request.GET.get("name", "").strip(),
        "code_number": request.GET.get("code_number", "").strip(),
        "part_number": request.GET.get("part_number", "").strip(),
        "category": request.GET.get("category", "").strip(),
        "period": request.GET.get("period", "30d").strip() or "30d",
    }


def _filtered_querysets(request):
    filters = _collect_filters(request)

    material_q = Q()
    if filters["name"]:
        material_q &= Q(name__icontains=filters["name"])
    if filters["code_number"]:
        material_q &= Q(code_number__icontains=filters["code_number"])
    if filters["part_number"]:
        material_q &= Q(part_number__icontains=filters["part_number"])
    if filters["category"]:
        material_q &= Q(category_id=filters["category"])

    materials = Material.objects.select_related("category", "subcategory", "equipment").filter(material_q)

    requisitions = Requisition.objects.select_related("material", "project", "requested_by").all()
    returns = MaterialReturn.objects.select_related("material", "project", "returned_by").all()
    transactions = StockTransaction.objects.select_related("material", "performed_by").all()

    if filters["name"]:
        requisitions = requisitions.filter(material__name__icontains=filters["name"])
        returns = returns.filter(material__name__icontains=filters["name"])
        transactions = transactions.filter(material__name__icontains=filters["name"])
    if filters["code_number"]:
        requisitions = requisitions.filter(code_number__icontains=filters["code_number"])
        returns = returns.filter(code_number__icontains=filters["code_number"])
        transactions = transactions.filter(code_number__icontains=filters["code_number"])
    if filters["part_number"]:
        requisitions = requisitions.filter(material__part_number__icontains=filters["part_number"])
        returns = returns.filter(material__part_number__icontains=filters["part_number"])
        transactions = transactions.filter(material__part_number__icontains=filters["part_number"])
    if filters["category"]:
        requisitions = requisitions.filter(material__category_id=filters["category"])
        returns = returns.filter(material__category_id=filters["category"])
        transactions = transactions.filter(material__category_id=filters["category"])

    period_start = _period_start(filters["period"])
    if period_start:
        requisitions = requisitions.filter(date_requested__gte=period_start)
        returns = returns.filter(date_returned__gte=period_start)
        transactions = transactions.filter(date__gte=period_start)

    return {
        "filters": filters,
        "materials": materials,
        "requisitions": requisitions,
        "returns": returns,
        "transactions": transactions,
        "period_start": period_start,
    }


def _base_context(request, active_tab):
    data = _filtered_querysets(request)
    unread_requisitions_count = 0
    can_access_scope_admin = False
    if request.user.is_authenticated:
        unread_requisitions_count = (
            Requisition.objects.exclude(requested_by=request.user)
            .exclude(read_receipts__user=request.user)
            .count()
        )
        can_access_scope_admin = (
            request.user.is_superuser
            or request.user.groups.filter(name="Operations Manager").exists()
        )

    return {
        **data,
        "active_tab": active_tab,
        "can_manage_current": _can_manage_section(request.user, active_tab),
        "can_access_scope_admin": can_access_scope_admin,
        "unread_requisitions_count": unread_requisitions_count,
        "category_choices": Category.objects.order_by("name"),
        "department_choices": DEPARTMENTS,
        "period_choices": [
            ("7d", "Last 7 days"),
            ("30d", "Last 30 days"),
            ("90d", "Last 90 days"),
            ("365d", "Last 12 months"),
            ("all", "All time"),
        ],
    }


SECTION_MANAGERS = {
    "materials": {"Storekeeper"},
    "requisitions": {"Storekeeper"},
    "projects": {"Storekeeper"},
    "returns": {"Storekeeper"},
    "transactions": {"Storekeeper"},
    "categories": {"Storekeeper"},
    "fleet": {"Fleet Officer"},
    "equipment": {"Fleet Officer", "Storekeeper"},
    "delivery": {"Storekeeper", "Fleet Officer"},
    "goods_received": {"Storekeeper"},
    "goods_issue": {"Storekeeper"},
    "goods_returns": {"Storekeeper"},
    "ppe": {"Storekeeper"},
    "overview": {"Storekeeper", "Fleet Officer"},
    "inventory": {"Storekeeper"},
    "warehouse": {"Storekeeper"},
    "scope": {"Operations Manager"},
    "roles": {"Operations Manager"},
    "audit": {"Operations Manager"},
    "settings": {"Operations Manager", "Storekeeper", "Fleet Officer"},
    "project_manage": {"Storekeeper"},
}


def _can_manage_section(user, section):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.groups.filter(name="Operations Manager").exists():
        return True
    allowed_groups = SECTION_MANAGERS.get(section, set())
    return user.groups.filter(name__in=allowed_groups).exists()


def _enforce_manage_access(user, section):
    if not _can_manage_section(user, section):
        raise PermissionDenied("You do not have permission to manage these records.")


def _scoped_store_ids(user):
    if not user.is_authenticated:
        return []
    if user.is_superuser or user.groups.filter(name="Operations Manager").exists():
        return None
    return list(UserStoreScope.objects.filter(user=user).values_list("store_location_id", flat=True))


def _filter_by_store_scope(qs, user, field_name):
    scoped_ids = _scoped_store_ids(user)
    if scoped_ids is None:
        return qs
    filter_key = f"{field_name}__in"
    return qs.filter(**{filter_key: scoped_ids})


def _enforce_store_manage_scope(user, store_location_id):
    if user.is_superuser or user.groups.filter(name="Operations Manager").exists():
        return
    has_scope = UserStoreScope.objects.filter(user=user, store_location_id=store_location_id, can_manage=True).exists()
    if not has_scope:
        raise PermissionDenied("You do not have manage access for this store location.")


def _project_store_context(request):
    project_id = (request.GET.get("project") or "").strip()
    if not project_id:
        return None, None, None

    try:
        project = Project.objects.get(pk=int(project_id))
    except (Project.DoesNotExist, ValueError, TypeError):
        return None, None, None

    stores_qs = _filter_by_store_scope(
        StoreLocation.objects.filter(project=project).order_by("name"),
        request.user,
        "id",
    )
    return project, stores_qs, list(stores_qs.values_list("id", flat=True))


def _project_context_for_list(request):
    """Resolve project context from ?project=<id> first, then exact ?name=<project name>."""
    project, _, _ = _project_store_context(request)
    if project:
        return project

    project_name = (request.GET.get("name") or "").strip()
    if not project_name:
        return None

    return Project.objects.filter(name__iexact=project_name).order_by("id").first()


def _log_action(request, action, entity, entity_id="", description=""):
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id or ""),
        description=description,
    )


def _due_meta(date_value):
    if not date_value:
        return {"label": "No date", "class_name": "badge-neutral", "rank": 0}

    today = timezone.localdate()
    if date_value < today:
        return {"label": "Overdue", "class_name": "badge-danger", "rank": 3}
    if date_value <= today + timedelta(days=30):
        return {"label": "Due soon", "class_name": "badge-warn", "rank": 2}
    return {"label": "On track", "class_name": "badge-ok", "rank": 1}


EXPORT_FIELDS = {
    "materials": [
        ("name", "Name"),
        ("code_number", "Code Number"),
        ("part_number", "Part Number"),
        ("serial_number", "Serial Number"),
        ("is_consumable", "Consumable"),
        ("measurement_unit", "Measurement"),
        ("category__name", "Category"),
        ("subcategory__name", "Subcategory"),
        ("quantity", "Quantity"),
        ("unit", "Unit"),
        ("min_required", "Min Required"),
        ("location", "Location"),
    ],
    "requisitions": [
        ("date_requested", "Date Requested"),
        ("material__name", "Material"),
        ("code_number", "Code Number"),
        ("material__part_number", "Part Number"),
        ("material__category__name", "Category"),
        ("quantity_requested", "Requested Quantity"),
        ("department", "Department"),
        ("project__name", "Project/Site"),
        ("status", "Status"),
        ("reserved_quantity", "Reserved Qty"),
        ("fulfilled", "Fulfilled"),
    ],
    "projects": [
        ("name", "Project Name"),
        ("location", "Location"),
        ("description", "Description"),
    ],
    "warehouses": [
        ("name", "Warehouse Name"),
        ("location", "Location"),
        ("description", "Description"),
        ("is_active", "Active"),
    ],
    "store-locations": [
        ("name", "Store Name"),
        ("location_type", "Type"),
        ("warehouse__name", "Warehouse"),
        ("project__name", "Project/Site"),
        ("is_active", "Active"),
    ],
    "storage-bins": [
        ("store_location__name", "Store"),
        ("bin_code", "BIN"),
        ("zone", "Zone"),
        ("aisle", "Aisle"),
        ("rack", "Rack"),
        ("shelf", "Shelf"),
        ("description", "Description"),
        ("is_active", "Active"),
    ],
    "inventory-balances": [
        ("material__name", "Material"),
        ("material__code_number", "Code Number"),
        ("storage_bin__store_location__name", "Store"),
        ("storage_bin__bin_code", "BIN"),
        ("on_hand", "On Hand"),
        ("reserved", "Reserved"),
        ("updated_at", "Updated"),
    ],
    "inventory-movements": [
        ("created_at", "Created At"),
        ("movement_type", "Type"),
        ("material__name", "Material"),
        ("material__code_number", "Code Number"),
        ("quantity", "Quantity"),
        ("from_store__name", "From Store"),
        ("from_bin__bin_code", "From BIN"),
        ("to_store__name", "To Store"),
        ("to_bin__bin_code", "To BIN"),
        ("reference_type", "Reference Type"),
        ("reference_number", "Reference Number"),
    ],
    "user-store-scopes": [
        ("user__username", "User"),
        ("store_location__name", "Store Location"),
        ("can_manage", "Can Manage"),
    ],
    "material-returns": [
        ("date_returned", "Date Returned"),
        ("material__name", "Material"),
        ("code_number", "Code Number"),
        ("project__name", "Project/Site"),
        ("quantity_returned", "Returned Quantity"),
        ("returned_by__username", "Returned By"),
    ],
    "stock-transactions": [
        ("date", "Date"),
        ("material__name", "Material"),
        ("code_number", "Code Number"),
        ("transaction_type", "Type"),
        ("quantity", "Quantity"),
        ("performed_by__username", "Performed By"),
    ],
    "categories": [
        ("name", "Category"),
    ],
    "subcategories": [
        ("name", "Subcategory"),
        ("category__name", "Category"),
    ],
    "equipment": [
        ("name", "Equipment"),
        ("serial_number", "Serial Number"),
        ("subcategory__name", "Subcategory"),
        ("subcategory__category__name", "Category"),
        ("project__name", "Project/Site"),
        ("location", "Location"),
        ("status", "Status"),
        ("purchase_date", "Purchase Date"),
        ("service_due_date", "Service Due Date"),
        ("is_active", "Active"),
    ],
    "drivers": [
        ("full_name", "Driver"),
        ("phone_number", "Phone"),
        ("license_number", "License Number"),
        ("license_expiry", "License Expiry"),
        ("is_active", "Active"),
    ],
    "mobile-equipment": [
        ("name", "Equipment"),
        ("registration_number", "Registration"),
        ("equipment_type", "Type"),
        ("status", "Status"),
        ("assigned_driver__full_name", "Assigned Driver"),
        ("project__name", "Project/Site"),
        ("service_due_date", "Service Due"),
        ("road_tax_due_date", "Road Tax Due"),
        ("fitness_due_date", "Fitness Due"),
        ("insurance_due_date", "Insurance Due"),
    ],
    "fleet-fuel-logs": [
        ("date_logged", "Date"),
        ("equipment__name", "Equipment"),
        ("fluid_type", "Fluid Type"),
        ("quantity", "Quantity"),
        ("unit", "Unit"),
        ("odometer_at_fill", "Odometer"),
        ("from_location", "From"),
        ("to_location", "To"),
    ],
    "fleet-maintenance": [
        ("equipment__name", "Equipment"),
        ("maintenance_type", "Maintenance Type"),
        ("status", "Status"),
        ("start_date", "Start"),
        ("end_date", "End"),
        ("cost", "Cost"),
        ("service_provider", "Service Provider"),
    ],
}


def _get_filtered_export_queryset(entity, request):
    cfg = _crud_cfg(entity)
    data = _filtered_querysets(request)

    if entity == "materials":
        return data["materials"].order_by("name")
    if entity == "requisitions":
        return data["requisitions"].order_by("-date_requested")
    if entity == "material-returns":
        return data["returns"].order_by("-date_returned")
    if entity == "stock-transactions":
        return data["transactions"].order_by("-date")
    if entity == "projects":
        return Project.objects.order_by("name")
    if entity == "warehouses":
        scoped_ids = _scoped_store_ids(request.user)
        qs = Warehouse.objects.order_by("name")
        if scoped_ids is not None:
            qs = qs.filter(store_locations__id__in=scoped_ids).distinct()
        return qs
    if entity == "categories":
        return Category.objects.order_by("name")
    if entity == "subcategories":
        return SubCategory.objects.select_related("category").order_by("name")
    if entity == "equipment":
        return _filter_by_store_scope(
            Equipment.objects.select_related("subcategory", "subcategory__category", "project", "store_location").order_by("name"),
            request.user,
            "store_location_id",
        )
    if entity == "drivers":
        return Driver.objects.order_by("full_name")
    if entity == "mobile-equipment":
        return _filter_by_store_scope(
            MobileEquipment.objects.select_related("assigned_driver", "project", "store_location").order_by("name"),
            request.user,
            "store_location_id",
        )
    if entity == "store-locations":
        return StoreLocation.objects.select_related("warehouse", "project").order_by("name")
    if entity == "storage-bins":
        return StorageBin.objects.select_related("store_location").order_by("store_location__name", "bin_code")
    if entity == "inventory-balances":
        return InventoryBalance.objects.select_related("material", "storage_bin", "storage_bin__store_location").order_by("material__name")
    if entity == "inventory-movements":
        return InventoryMovement.objects.select_related(
            "material", "from_store", "from_bin", "to_store", "to_bin", "created_by"
        ).order_by("-created_at")
    if entity == "user-store-scopes":
        return UserStoreScope.objects.select_related("user", "store_location").order_by("user__username", "store_location__name")
    if entity == "fleet-fuel-logs":
        return _filter_by_store_scope(
            FleetFuelLog.objects.select_related("equipment", "equipment__store_location", "consumable").order_by("-date_logged"),
            request.user,
            "equipment__store_location_id",
        )
    if entity == "fleet-maintenance":
        return _filter_by_store_scope(
            FleetMaintenance.objects.select_related("equipment", "equipment__store_location").order_by("-start_date"),
            request.user,
            "equipment__store_location_id",
        )

    return cfg["model"].objects.all()


CRUD_REGISTRY = {
    "materials": {
        "model": Material,
        "form": MaterialForm,
        "route": "materials",
        "active_tab": "materials",
        "label": "Material",
    },
    "requisitions": {
        "model": Requisition,
        "form": RequisitionForm,
        "route": "requisitions",
        "active_tab": "requisitions",
        "label": "Requisition",
    },
    "projects": {
        "model": Project,
        "form": ProjectForm,
        "route": "projects",
        "active_tab": "projects",
        "label": "Project",
    },
    "warehouses": {
        "model": Warehouse,
        "form": WarehouseForm,
        "route": "warehouse_management",
        "active_tab": "warehouse",
        "label": "Warehouse",
    },
    "store-locations": {
        "model": StoreLocation,
        "form": StoreLocationForm,
        "route": "inventory_management",
        "active_tab": "inventory",
        "label": "Store Location",
    },
    "storage-bins": {
        "model": StorageBin,
        "form": StorageBinForm,
        "route": "inventory_management",
        "active_tab": "inventory",
        "label": "Storage Bin",
    },
    "inventory-balances": {
        "model": InventoryBalance,
        "form": InventoryBalanceForm,
        "route": "inventory_management",
        "active_tab": "inventory",
        "label": "Inventory Balance",
    },
    "inventory-movements": {
        "model": InventoryMovement,
        "form": InventoryMovementForm,
        "route": "inventory_management",
        "active_tab": "inventory",
        "label": "Inventory Movement",
    },
    "user-store-scopes": {
        "model": UserStoreScope,
        "form": UserStoreScopeForm,
        "route": "store_scope",
        "active_tab": "scope",
        "label": "User Store Scope",
    },
    "material-returns": {
        "model": MaterialReturn,
        "form": MaterialReturnForm,
        "route": "material_returns",
        "active_tab": "returns",
        "label": "Material Return",
    },
    "stock-transactions": {
        "model": StockTransaction,
        "form": StockTransactionForm,
        "route": "stock_transactions",
        "active_tab": "transactions",
        "label": "Stock Transaction",
    },
    "categories": {
        "model": Category,
        "form": CategoryForm,
        "route": "categories",
        "active_tab": "categories",
        "label": "Category",
    },
    "subcategories": {
        "model": SubCategory,
        "form": SubCategoryForm,
        "route": "categories",
        "active_tab": "categories",
        "label": "SubCategory",
    },
    "equipment": {
        "model": Equipment,
        "form": EquipmentForm,
        "route": "equipment_management",
        "active_tab": "equipment",
        "label": "Equipment",
    },
    "drivers": {
        "model": Driver,
        "form": DriverForm,
        "route": "fleet_management",
        "active_tab": "fleet",
        "label": "Driver",
    },
    "mobile-equipment": {
        "model": MobileEquipment,
        "form": MobileEquipmentForm,
        "route": "fleet_management",
        "active_tab": "fleet",
        "label": "Mobile Equipment",
    },
    "fleet-fuel-logs": {
        "model": FleetFuelLog,
        "form": FleetFuelLogForm,
        "route": "fleet_management",
        "active_tab": "fleet",
        "label": "Fleet Fuel Log",
    },
    "fleet-maintenance": {
        "model": FleetMaintenance,
        "form": FleetMaintenanceForm,
        "route": "fleet_management",
        "active_tab": "fleet",
        "label": "Fleet Maintenance",
    },
}


def _crud_cfg(entity):
    cfg = CRUD_REGISTRY.get(entity)
    if not cfg:
        raise Http404("Unknown entity")
    return cfg


def _is_ops_manager(user):
    return user.is_superuser or user.groups.filter(name="Operations Manager").exists()


@login_required
def workspace_home(request):
    context = _base_context(request, "home")
    materials = context["materials"]
    requisitions = context["requisitions"]
    transactions = context["transactions"]

    low_stock = materials.filter(quantity__lte=F("min_required")).order_by("name")
    recent_transactions = transactions.order_by("-date")[:10]

    category_counts = list(
        materials.values("category__name").annotate(material_count=Count("id")).order_by("category__name")
    )
    transaction_counts = list(
        transactions.values("transaction_type").annotate(count=Count("id")).order_by("transaction_type")
    )
    requisition_counts = list(
        requisitions.values("department").annotate(count=Count("id")).order_by("department")
    )
    material_counts = list(materials.values("name", "quantity").order_by("-quantity")[:10])

    context.update(
        {
            "total_materials": materials.count(),
            "low_stock_count": low_stock.count(),
            "total_categories": Category.objects.count(),
            "active_equipments": Equipment.objects.filter(is_active=True).count(),
            "active_fleets": MobileEquipment.objects.filter(is_active=True).count(),
            "total_requisitions": requisitions.count(),
            "pending_requisitions": requisitions.filter(fulfilled=False).count(),
            "total_transactions": transactions.count(),
            "total_quantity": materials.aggregate(total=Sum("quantity"))["total"] or 0,
            "low_stock": low_stock[:10],
            "recent_transactions": recent_transactions,
            "category_counts_json": json.dumps(category_counts),
            "transaction_counts_json": json.dumps(transaction_counts),
            "requisition_counts_json": json.dumps(requisition_counts),
            "material_counts_json": json.dumps(material_counts),
        }
    )
    return render(request, "SupplChain_MNG/workspace_home.html", context)


@login_required
def inventory_management_view(request):
    context = _base_context(request, "inventory")
    name_filter = context["filters"]["name"]
    code_filter = context["filters"]["code_number"]

    warehouse_rows = Warehouse.objects.order_by("name")
    scoped_ids = _scoped_store_ids(request.user)
    if scoped_ids is not None:
        warehouse_rows = warehouse_rows.filter(store_locations__id__in=scoped_ids).distinct()
    if name_filter:
        warehouse_rows = warehouse_rows.filter(Q(name__icontains=name_filter) | Q(location__icontains=name_filter))

    store_rows = _filter_by_store_scope(
        StoreLocation.objects.select_related("warehouse", "project").order_by("name"),
        request.user,
        "id",
    )
    if name_filter:
        store_rows = store_rows.filter(
            Q(name__icontains=name_filter)
            | Q(project__name__icontains=name_filter)
            | Q(warehouse__name__icontains=name_filter)
        )

    bin_rows = _filter_by_store_scope(
        StorageBin.objects.select_related("store_location").order_by("store_location__name", "bin_code"),
        request.user,
        "store_location_id",
    )
    if name_filter:
        bin_rows = bin_rows.filter(Q(store_location__name__icontains=name_filter) | Q(bin_code__icontains=name_filter))

    balance_rows = _filter_by_store_scope(
        InventoryBalance.objects.select_related("material", "storage_bin", "storage_bin__store_location").order_by(
            "material__name", "storage_bin__store_location__name", "storage_bin__bin_code"
        ),
        request.user,
        "storage_bin__store_location_id",
    )
    if name_filter:
        balance_rows = balance_rows.filter(material__name__icontains=name_filter)
    if code_filter:
        balance_rows = balance_rows.filter(material__code_number__icontains=code_filter)

    scope_rows = UserStoreScope.objects.select_related("user", "store_location")
    if context["can_access_scope_admin"]:
        scope_rows = scope_rows.order_by("user__username", "store_location__name")
    else:
        scope_rows = scope_rows.filter(user=request.user).order_by("store_location__name")

    warehouse_insights = []
    stale_cutoff = timezone.now() - timedelta(days=90)
    for wh in warehouse_rows:
        wh_store_ids = list(store_rows.filter(warehouse=wh).values_list("id", flat=True))
        wh_balances = balance_rows.filter(storage_bin__store_location_id__in=wh_store_ids)

        top_materials = list(
            wh_balances.values("material__name")
            .annotate(total=Sum("on_hand"))
            .order_by("-total")[:5]
        )

        low_stock_count = wh_balances.filter(on_hand__lte=F("material__min_required")).values("material_id").distinct().count()

        last_moves = {
            row["material_id"]: row["last_move"]
            for row in InventoryMovement.objects.filter(
                Q(from_store_id__in=wh_store_ids) | Q(to_store_id__in=wh_store_ids)
            )
            .values("material_id")
            .annotate(last_move=Max("created_at"))
        }

        dead_stock_count = 0
        active_materials = wh_balances.filter(on_hand__gt=0).values("material_id").annotate(total=Sum("on_hand"))
        for line in active_materials:
            last_move = last_moves.get(line["material_id"])
            if not last_move or last_move < stale_cutoff:
                dead_stock_count += 1

        warehouse_insights.append(
            {
                "warehouse": wh,
                "top_materials": top_materials,
                "low_stock_count": low_stock_count,
                "dead_stock_count": dead_stock_count,
                "total_qty": wh_balances.aggregate(total=Sum("on_hand"))["total"] or 0,
            }
        )

    context.update(
        {
            "warehouse_rows": warehouse_rows,
            "warehouse_insights": warehouse_insights,
            "store_rows": store_rows,
            "bin_rows": bin_rows[:120],
            "balance_rows": balance_rows[:200],
            "scope_rows": scope_rows[:80],
            "active_warehouse_count": warehouse_rows.filter(is_active=True).count(),
            "warehouse_store_count": store_rows.filter(warehouse__isnull=False).count(),
            "warehouse_stock_lines": balance_rows.filter(storage_bin__store_location__warehouse__isnull=False, on_hand__gt=0).count(),
            "warehouse_low_stock_materials": balance_rows.filter(
                storage_bin__store_location__warehouse__isnull=False,
                on_hand__lte=F("material__min_required"),
            ).values("material_id").distinct().count(),
            "active_store_count": store_rows.filter(is_active=True).count(),
            "active_bin_count": bin_rows.filter(is_active=True).count(),
            "stock_line_count": balance_rows.filter(on_hand__gt=0).count(),
            "reserved_total": balance_rows.aggregate(total=Sum("reserved"))["total"] or 0,
        }
    )
    return render(request, "SupplChain_MNG/inventory_management.html", context)


@login_required
def warehouse_transfer_preset_view(request):
    _enforce_manage_access(request.user, "inventory")
    form = WarehouseTransferPresetForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        source_store = cd["source_store"]
        source_bin = cd["source_bin"]
        destination_store = cd["destination_store"]
        destination_bin = cd["destination_bin"]

        if source_bin.store_location_id != source_store.id:
            form.add_error("source_bin", "Source BIN must belong to selected source store.")
        if destination_bin.store_location_id != destination_store.id:
            form.add_error("destination_bin", "Destination BIN must belong to selected destination store.")

        if not form.errors:
            _enforce_store_manage_scope(request.user, source_store.id)
            _enforce_store_manage_scope(request.user, destination_store.id)
            try:
                InventoryMovement.objects.create(
                    movement_type="TRANSFER",
                    material=cd["material"],
                    quantity=cd["quantity"],
                    from_store=source_store,
                    from_bin=source_bin,
                    to_store=destination_store,
                    to_bin=destination_bin,
                    reference_type="WAREHOUSE_TRANSFER",
                    reference_number=cd.get("reference_number") or "",
                    notes=cd.get("notes") or "",
                    created_by=request.user,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Warehouse-to-site transfer posted successfully.")
                return redirect("inventory_management")

    context = _base_context(request, "inventory")
    context.update(
        {
            "form": form,
            "title": "Warehouse Transfer Preset",
            "cancel_url": reverse("inventory_management"),
        }
    )
    return render(request, "SupplChain_MNG/warehouse_transfer_preset_form.html", context)


@login_required
def store_scope_view(request):
    context = _base_context(request, "scope")
    if not context["can_access_scope_admin"]:
        raise PermissionDenied("You do not have permission to access store scope management.")

    name_filter = context["filters"]["name"]
    scope_rows = UserStoreScope.objects.select_related("user", "store_location").order_by(
        "user__username", "store_location__name"
    )
    if name_filter:
        scope_rows = scope_rows.filter(
            Q(user__username__icontains=name_filter) | Q(store_location__name__icontains=name_filter)
        )

    context.update(
        {
            "scope_rows": scope_rows[:250],
            "scope_total": scope_rows.count(),
            "scope_manage_total": scope_rows.filter(can_manage=True).count(),
            "scope_user_total": scope_rows.values("user_id").distinct().count(),
            "scope_store_total": scope_rows.values("store_location_id").distinct().count(),
        }
    )
    return render(request, "SupplChain_MNG/store_scope_management.html", context)


@login_required
def materials_view(request):
    context = _base_context(request, "materials")
    rows = list(context["materials"].order_by("name"))
    for item in rows:
        item.stock_meta = _due_meta(timezone.localdate() if item.needs_restock() else timezone.localdate() + timedelta(days=31))
    context["rows"] = rows
    return render(request, "SupplChain_MNG/materials.html", context)


@login_required
def material_detail_view(request, pk):
    context = _base_context(request, "materials")
    material = get_object_or_404(
        Material.objects.select_related("category", "subcategory", "equipment"),
        pk=pk,
    )
    context.update(
        {
            "material": material,
            "recent_transactions": StockTransaction.objects.filter(material=material).select_related("performed_by").order_by("-date")[:12],
            "recent_requisitions": Requisition.objects.filter(material=material).select_related("project", "requested_by").order_by("-date_requested")[:12],
            "recent_returns": MaterialReturn.objects.filter(material=material).select_related("project", "returned_by").order_by("-date_returned")[:12],
            "stock_meta": _due_meta(timezone.localdate() if material.needs_restock() else timezone.localdate() + timedelta(days=31)),
        }
    )
    return render(request, "SupplChain_MNG/material_detail.html", context)


@login_required
def requisitions_view(request):
    def _release_reservations(req):
        for line in req.reservations.select_related("inventory_balance"):
            bal = line.inventory_balance
            new_reserved = bal.reserved - line.quantity
            bal.reserved = new_reserved if new_reserved > 0 else Decimal("0.00")
            bal.save(update_fields=["reserved", "updated_at"])
        req.reservations.all().delete()
        req.reserved_quantity = Decimal("0.00")

    def _reservation_targets(req):
        line_targets = []
        for item in req.items.select_related("material"):
            qty = Decimal(str(item.quantity_requested or 0))
            if qty <= 0:
                continue
            line_targets.append((item.material, qty))

        if line_targets:
            return line_targets

        # Backward compatibility for older single-material requisitions.
        if req.material and Decimal(str(req.quantity_requested or 0)) > 0:
            return [(req.material, Decimal(str(req.quantity_requested)))]

        raise ValidationError("Requisition has no valid material lines to reserve.")

    def _reserve_hq_stock(req):
        targets = _reservation_targets(req)
        total_reserved = Decimal("0.00")

        for material, target_qty in targets:
            balances = list(
                InventoryBalance.objects.select_related("storage_bin", "storage_bin__store_location")
                .filter(material=material, storage_bin__store_location__location_type="HQ")
                .order_by("storage_bin__store_location__name", "storage_bin__bin_code")
            )
            available_total = sum([(bal.on_hand - bal.reserved) for bal in balances], Decimal("0.00"))
            if available_total < target_qty:
                raise ValidationError(
                    f"Insufficient HQ stock for {material.name}. Available: {available_total}, required: {target_qty}."
                )

            remaining = target_qty
            reservation_lines = []
            for bal in balances:
                if remaining <= 0:
                    break
                available = bal.on_hand - bal.reserved
                if available <= 0:
                    continue
                take = min(available, remaining)
                bal.reserved += take
                bal.save(update_fields=["reserved", "updated_at"])
                reservation_lines.append(RequisitionReservation(requisition=req, inventory_balance=bal, quantity=take))
                remaining -= take

            if remaining > 0:
                raise ValidationError("Could not complete stock reservation allocation.")

            RequisitionReservation.objects.bulk_create(reservation_lines)
            total_reserved += target_qty

        req.reserved_quantity = total_reserved

    context = _base_context(request, "requisitions")
    project_context = _project_context_for_list(request)

    if request.method == "POST":
        _enforce_manage_access(request.user, "requisitions")
        req_id = request.POST.get("requisition_id")
        action = request.POST.get("action")
        reason = (request.POST.get("rejection_reason") or "").strip()

        req = get_object_or_404(Requisition, pk=req_id)
        try:
            with transaction.atomic():
                if action == "submit":
                    if req.status == "DRAFT":
                        req.status = "SUBMITTED"
                        req.submitted_at = timezone.now()
                        req.save(update_fields=["status", "submitted_at", "fulfilled"])
                        _log_action(request, "UPDATE", "Requisition", req.id, f"Submitted requisition {req.id}")
                elif action == "validate":
                    if req.status in {"SUBMITTED", "DRAFT"}:
                        req.status = "VALIDATED"
                        req.validated_by = request.user
                        req.validated_at = timezone.now()
                        req.save(update_fields=["status", "validated_by", "validated_at", "fulfilled"])
                        _log_action(request, "UPDATE", "Requisition", req.id, f"Validated requisition {req.id}")
                elif action == "approve":
                    if req.status in {"SUBMITTED", "VALIDATED"}:
                        _release_reservations(req)
                        _reserve_hq_stock(req)
                        req.status = "APPROVED"
                        req.approved_by = request.user
                        req.approved_at = timezone.now()
                        req.rejected_by = None
                        req.rejected_at = None
                        req.rejection_reason = ""
                        req.save(
                            update_fields=[
                                "status",
                                "approved_by",
                                "approved_at",
                                "reserved_quantity",
                                "rejected_by",
                                "rejected_at",
                                "rejection_reason",
                                "fulfilled",
                            ]
                        )
                        _log_action(request, "UPDATE", "Requisition", req.id, f"Approved requisition {req.id} with reservation")
                elif action == "reject":
                    _release_reservations(req)
                    req.status = "REJECTED"
                    req.rejected_by = request.user
                    req.rejected_at = timezone.now()
                    req.rejection_reason = reason
                    req.save(
                        update_fields=[
                            "status",
                            "reserved_quantity",
                            "rejected_by",
                            "rejected_at",
                            "rejection_reason",
                            "fulfilled",
                        ]
                    )
                    _log_action(request, "UPDATE", "Requisition", req.id, f"Rejected requisition {req.id}")
                else:
                    messages.warning(request, "Unsupported requisition action.")
                    return redirect("requisitions")

                messages.success(request, f"Requisition {req.req_number or req.id} action '{action}' completed.")
        except ValidationError as exc:
            messages.error(request, str(exc))

        if project_context:
            return redirect(f"{request.path}?project={project_context.id}")
        return redirect("requisitions")

    req_qs = (
        context["requisitions"]
        .select_related("material", "project", "requested_by")
        .prefetch_related("items", "items__material")
        .order_by("-date_requested")
    )

    if project_context:
        req_qs = req_qs.filter(project=project_context)

    rows = list(req_qs)

    for req in rows:
        line_items = list(req.items.all())
        if line_items:
            req.line_count = len(line_items)
            req.total_qty = sum([Decimal(str(item.quantity_requested)) for item in line_items], Decimal("0.00"))
        else:
            req.line_count = 1 if req.material else 0
            req.total_qty = Decimal(str(req.quantity_requested or 0))

    unread_ids = list(
        Requisition.objects.exclude(requested_by=request.user)
        .exclude(read_receipts__user=request.user)
        .values_list("id", flat=True)
    )
    if unread_ids:
        RequisitionReadReceipt.objects.bulk_create(
            [RequisitionReadReceipt(user=request.user, requisition_id=req_id) for req_id in unread_ids],
            ignore_conflicts=True,
        )

    context["rows"] = rows
    context["project_context"] = project_context
    context["unread_requisitions_count"] = 0
    return render(request, "SupplChain_MNG/requisitions.html", context)


@login_required
def requisition_detail_view(request, pk):
    context = _base_context(request, "requisitions")
    req = get_object_or_404(
        Requisition.objects.select_related("material", "project", "requested_by", "validated_by", "approved_by", "rejected_by")
        .prefetch_related("items__material", "reservations__inventory_balance__storage_bin__store_location"),
        pk=pk,
    )

    line_items = list(req.items.select_related("material"))
    if not line_items and req.material:
        line_items = [req]

    reservation_lines = list(req.reservations.select_related("inventory_balance__storage_bin__store_location"))

    context.update(
        {
            "req": req,
            "line_items": line_items,
            "reservation_lines": reservation_lines,
            "project_context": _project_context_for_list(request),
        }
    )
    return render(request, "SupplChain_MNG/requisition_detail.html", context)


@login_required
def projects_view(request):
    context = _base_context(request, "projects")
    context["rows"] = (
        Project.objects.annotate(
            requisition_count=Count("requisition", distinct=True),
            returns_count=Count("materialreturn", distinct=True),
        )
        .order_by("name")
    )
    return render(request, "SupplChain_MNG/projects.html", context)


@login_required
def warehouse_management_view(request):
    context = _base_context(request, "warehouse")
    warehouses = Warehouse.objects.order_by("name")
    scoped_ids = _scoped_store_ids(request.user)
    if scoped_ids is not None:
        warehouses = warehouses.filter(store_locations__id__in=scoped_ids).distinct()

    store_rows = _filter_by_store_scope(
        StoreLocation.objects.select_related("project", "warehouse").order_by("name"),
        request.user,
        "id",
    )
    bin_rows = _filter_by_store_scope(
        StorageBin.objects.select_related("store_location", "store_location__warehouse").order_by("store_location__name", "bin_code"),
        request.user,
        "store_location_id",
    )
    balance_rows = _filter_by_store_scope(
        InventoryBalance.objects.select_related("storage_bin", "storage_bin__store_location", "material").order_by("material__name"),
        request.user,
        "storage_bin__store_location_id",
    )

    cards = []
    for wh in warehouses:
        wh_store_ids = list(store_rows.filter(warehouse=wh).values_list("id", flat=True))
        wh_project_ids = list(
            store_rows.filter(warehouse=wh, project__isnull=False).values_list("project_id", flat=True).distinct()
        )
        wh_requisitions = Requisition.objects.filter(project_id__in=wh_project_ids)
        wh_returns = MaterialReturn.objects.filter(project_id__in=wh_project_ids)

        cards.append(
            {
                "warehouse": wh,
                "store_count": len(wh_store_ids),
                "project_count": len(wh_project_ids),
                "bin_count": bin_rows.filter(store_location_id__in=wh_store_ids).count(),
                "stock_qty": balance_rows.filter(storage_bin__store_location_id__in=wh_store_ids).aggregate(total=Sum("on_hand"))["total"] or 0,
                "pending_requisitions": wh_requisitions.filter(fulfilled=False).count(),
                "returns_qty": wh_returns.aggregate(total=Sum("quantity_returned"))["total"] or 0,
            }
        )

    context.update(
        {
            "warehouse_cards": cards,
            "warehouse_count": warehouses.count(),
            "active_warehouse_count": warehouses.filter(is_active=True).count(),
            "warehouse_store_count": store_rows.filter(warehouse__isnull=False).count(),
            "warehouse_project_count": store_rows.filter(warehouse__isnull=False, project__isnull=False).values("project_id").distinct().count(),
            "warehouse_stock_lines": balance_rows.filter(storage_bin__store_location__warehouse__isnull=False, on_hand__gt=0).count(),
        }
    )
    return render(request, "SupplChain_MNG/warehouse_management.html", context)


@login_required
def warehouse_manage_view(request, pk):
    context = _base_context(request, "warehouse")
    warehouse = get_object_or_404(Warehouse, pk=pk)
    _enforce_manage_access(request.user, "warehouse")

    scoped_ids = _scoped_store_ids(request.user)
    stores_qs = StoreLocation.objects.select_related("project", "warehouse").filter(warehouse=warehouse).order_by("name")
    if scoped_ids is not None:
        stores_qs = stores_qs.filter(id__in=scoped_ids)

    bins_qs = StorageBin.objects.select_related("store_location").filter(store_location__warehouse=warehouse).order_by(
        "store_location__name", "zone", "aisle", "rack", "shelf", "bin_code"
    )
    balances_qs = InventoryBalance.objects.select_related("material", "storage_bin", "storage_bin__store_location").filter(
        storage_bin__store_location__warehouse=warehouse
    )

    if scoped_ids is not None:
        bins_qs = bins_qs.filter(store_location_id__in=scoped_ids)
        balances_qs = balances_qs.filter(storage_bin__store_location_id__in=scoped_ids)

    wh_store_ids = list(stores_qs.values_list("id", flat=True))

    recent_movements = list(
        InventoryMovement.objects.select_related(
            "material", "from_store", "to_store", "from_bin", "to_bin", "created_by"
        )
        .filter(Q(from_store_id__in=wh_store_ids) | Q(to_store_id__in=wh_store_ids))
        .order_by("-created_at")[:50]
    )

    linked_projects = list(
        Project.objects.filter(store_locations__warehouse=warehouse).distinct().order_by("name")
    )

    project_cards = []
    for project in linked_projects:
        project_store_ids = list(
            stores_qs.filter(project=project).values_list("id", flat=True)
        )
        if not project_store_ids:
            continue

        sent_qty = InventoryMovement.objects.filter(from_store_id__in=project_store_ids).aggregate(total=Sum("quantity"))["total"] or 0
        received_qty = InventoryMovement.objects.filter(to_store_id__in=project_store_ids).aggregate(total=Sum("quantity"))["total"] or 0
        in_store_qty = balances_qs.filter(storage_bin__store_location_id__in=project_store_ids).aggregate(total=Sum("on_hand"))["total"] or 0
        pending_requisitions = Requisition.objects.filter(project=project, fulfilled=False).count()
        returned_goods_qty = MaterialReturn.objects.filter(project=project).aggregate(total=Sum("quantity_returned"))["total"] or 0

        project_cards.append(
            {
                "project": project,
                "sent_qty": sent_qty,
                "received_qty": received_qty,
                "in_store_qty": in_store_qty,
                "pending_requisitions": pending_requisitions,
                "returned_goods_qty": returned_goods_qty,
            }
        )

    store_form = StoreLocationForm(prefix="store")
    store_form.fields["warehouse"].queryset = Warehouse.objects.filter(pk=warehouse.pk)
    store_form.fields["warehouse"].initial = warehouse.pk

    bin_form = StorageBinForm(prefix="bin")
    bin_form.fields["store_location"].queryset = stores_qs

    link_form = WarehouseProjectLinkForm(prefix="link")
    if scoped_ids is not None:
        link_form.fields["site_store"].queryset = link_form.fields["site_store"].queryset.filter(id__in=scoped_ids)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_store":
            store_form = StoreLocationForm(request.POST, prefix="store")
            store_form.fields["warehouse"].queryset = Warehouse.objects.filter(pk=warehouse.pk)
            if store_form.is_valid():
                store = store_form.save(commit=False)
                store.warehouse = warehouse
                store.save()
                messages.success(request, "Store linked to warehouse successfully.")
                return redirect("warehouse_manage", pk=warehouse.pk)

        elif action == "create_bin":
            bin_form = StorageBinForm(request.POST, prefix="bin")
            bin_form.fields["store_location"].queryset = stores_qs
            if bin_form.is_valid():
                storage_bin = bin_form.save(commit=False)
                if storage_bin.store_location.warehouse_id != warehouse.id:
                    bin_form.add_error("store_location", "Selected store does not belong to this warehouse.")
                else:
                    storage_bin.save()
                    messages.success(request, "Bin created successfully.")
                    return redirect("warehouse_manage", pk=warehouse.pk)

        elif action == "link_project":
            link_form = WarehouseProjectLinkForm(request.POST, prefix="link")
            if scoped_ids is not None:
                link_form.fields["site_store"].queryset = link_form.fields["site_store"].queryset.filter(id__in=scoped_ids)

            if link_form.is_valid():
                site_store = link_form.cleaned_data["site_store"]
                project = link_form.cleaned_data["project"]
                site_store.project = project
                site_store.warehouse = warehouse
                site_store.save(update_fields=["project", "warehouse"])
                messages.success(request, "Project/site linked to this warehouse successfully.")
                return redirect("warehouse_manage", pk=warehouse.pk)

        elif action == "allocate_material":
            material_id = request.POST.get("alloc_material")
            bin_id = request.POST.get("alloc_bin")
            if not material_id or not bin_id:
                messages.error(request, "Please select both a material and a bin.")
                return redirect("warehouse_manage", pk=warehouse.pk)
            alloc_material = get_object_or_404(Material, pk=material_id)
            target_bin = get_object_or_404(StorageBin, pk=bin_id, store_location__warehouse=warehouse)
            existing_balances = list(
                InventoryBalance.objects.filter(
                    material=alloc_material,
                    storage_bin__store_location__warehouse=warehouse,
                )
            )
            total_on_hand = sum(b.on_hand for b in existing_balances)
            total_reserved = sum(b.reserved for b in existing_balances)
            # Move any existing stock from other bins to the target bin
            for b in existing_balances:
                if b.storage_bin_id != target_bin.id:
                    b.delete()
            # Upsert balance at target bin (creates a zero-balance record if none existed)
            target_balance, created = InventoryBalance.objects.get_or_create(
                material=alloc_material,
                storage_bin=target_bin,
                defaults={"on_hand": total_on_hand, "reserved": total_reserved},
            )
            if not created:
                target_balance.on_hand = total_on_hand
                target_balance.reserved = total_reserved
                target_balance.save(update_fields=["on_hand", "reserved", "updated_at"])
            bin_label = " / ".join(filter(None, [target_bin.zone, target_bin.aisle, target_bin.rack, target_bin.shelf, target_bin.bin_code]))
            if created and total_on_hand == 0:
                messages.success(request, f"{alloc_material.name} allocated to {bin_label}. No stock yet — use Stock In to add quantity.")
            else:
                messages.success(request, f"{alloc_material.name} allocated to {bin_label}.")
            return redirect("warehouse_manage", pk=warehouse.pk)

    # Materials summary — aggregate per material across all bins in this warehouse
    materials_summary = list(
        balances_qs.filter(on_hand__gt=0)
        .values("material__id", "material__name", "material__code_number")
        .annotate(
            total_on_hand=Sum("on_hand"),
            total_reserved=Sum("reserved"),
        )
        .order_by("material__name")
    )
    for m in materials_summary:
        m["available"] = m["total_on_hand"] - m["total_reserved"]

    # Layout data — hierarchical Zone → Aisle → Rack → Shelf → Bin
    # Bins only go as deep as their actual fields; empty levels are skipped entirely.
    # Include ALL allocated bins (even zero-stock) so allocations are always visible.
    _tree = {}  # zone → {"__bins__": {}, "aisles": {aisle → {"__bins__": {}, "racks": {rack → {"__bins__": {}, "shelves": {shelf → {bin_code: [items]}}}}}}}}
    for b in balances_qs.select_related(
        "material", "storage_bin", "storage_bin__store_location"
    )[:500]:
        zone_key = b.storage_bin.zone or ""
        aisle_key = b.storage_bin.aisle or ""
        rack_key = b.storage_bin.rack or ""
        shelf_key = b.storage_bin.shelf or ""
        bin_code = b.storage_bin.bin_code
        item = {
                "balance_id": b.pk,
                "material_name": b.material.name,
                "material_code": b.material.code_number,
                "on_hand": b.on_hand,
                "reserved": b.reserved,
                "available": b.on_hand - b.reserved,
                "min_required": b.min_required,
                "status": (
                    "out_of_stock" if b.on_hand <= 0
                    else "low_stock" if b.min_required > 0 and b.on_hand <= b.min_required
                    else "in_stock"
                ),
            }
        sid = b.storage_bin.store_location_id
        if zone_key not in _tree:
            _tree[zone_key] = {"__bins__": {}, "aisles": {}, "__store_id__": sid}
        if not aisle_key:
            _tree[zone_key]["__bins__"].setdefault(bin_code, []).append(item)
        else:
            _z = _tree[zone_key]["aisles"]
            if aisle_key not in _z:
                _z[aisle_key] = {"__bins__": {}, "racks": {}, "__store_id__": sid}
            if not rack_key:
                _z[aisle_key]["__bins__"].setdefault(bin_code, []).append(item)
            else:
                _a = _z[aisle_key]["racks"]
                if rack_key not in _a:
                    _a[rack_key] = {"__bins__": {}, "shelves": {}, "__store_id__": sid}
                if not shelf_key:
                    _a[rack_key]["__bins__"].setdefault(bin_code, []).append(item)
                else:
                    if shelf_key not in _a[rack_key]["shelves"]:
                        _a[rack_key]["shelves"][shelf_key] = {"__store_id__": sid, "__bins__": {}}
                    _a[rack_key]["shelves"][shelf_key]["__bins__"].setdefault(bin_code, []).append(item)

    def _bin_list(d):
        return [{"bin_code": bc, "items": items} for bc, items in sorted(d.items())]

    layout_data = []
    for zone_key in sorted(_tree):
        zd = _tree[zone_key]
        zone_obj = {
            "zone": zone_key or "(No Zone)",
            "zone_val": zone_key,
            "store_location_id": zd.get("__store_id__", 0),
            "bins_direct": _bin_list(zd["__bins__"]),
            "aisles": [],
        }
        for aisle_key in sorted(zd["aisles"]):
            ad = zd["aisles"][aisle_key]
            aisle_obj = {
                "aisle": aisle_key,
                "aisle_val": aisle_key,
                "store_location_id": ad.get("__store_id__", 0),
                "bins_direct": _bin_list(ad["__bins__"]),
                "racks": [],
            }
            for rack_key in sorted(ad["racks"]):
                rd = ad["racks"][rack_key]
                rack_obj = {
                    "rack": rack_key,
                    "rack_val": rack_key,
                    "store_location_id": rd.get("__store_id__", 0),
                    "bins_direct": _bin_list(rd["__bins__"]),
                    "shelves": [],
                }
                for shelf_key in sorted(rd["shelves"]):
                    sd = rd["shelves"][shelf_key]
                    rack_obj["shelves"].append({
                        "shelf": shelf_key,
                        "shelf_val": shelf_key,
                        "store_location_id": sd.get("__store_id__", 0),
                        "bins": _bin_list(sd["__bins__"]),
                    })
                aisle_obj["racks"].append(rack_obj)
            zone_obj["aisles"].append(aisle_obj)
        layout_data.append(zone_obj)

    balance_rows = [
        {
            "material": b.material,
            "storage_bin": b.storage_bin,
            "on_hand": b.on_hand,
            "reserved": b.reserved,
            "available": b.on_hand - b.reserved,
        }
        for b in balances_qs.filter(on_hand__gt=0).select_related(
            "material", "storage_bin", "storage_bin__store_location"
        )[:300]
    ]

    # All materials for allocation dialog (searchable — user should see everything)
    all_materials = list(Material.objects.order_by("name").values("id", "name", "code_number"))

    # For backward compat: materials that have stock here (used for info message)
    alloc_materials_with_stock_ids = set(
        InventoryBalance.objects.filter(
            storage_bin__store_location__warehouse=warehouse,
            on_hand__gt=0,
        ).values_list("material_id", flat=True)
    )

    # Store → bins mapping as JSON for 5-level cascade in allocation dialog
    stores_bins_json = {}
    for b in bins_qs.filter(is_active=True):
        sid = str(b.store_location_id)
        stores_bins_json.setdefault(sid, []).append(
            {
                "id": b.id,
                "zone": b.zone or "",
                "aisle": b.aisle or "",
                "rack": b.rack or "",
                "shelf": b.shelf or "",
                "bin_code": b.bin_code,
            }
        )

    alloc_store_rows = [store for store in stores_qs if str(store.id) in stores_bins_json]

    # All warehouses for the jump selector
    all_warehouses = list(Warehouse.objects.filter(is_active=True).order_by("name"))

    context.update(
        {
            "warehouse": warehouse,
            "store_rows": list(stores_qs),
            "bin_rows": list(bins_qs[:300]),
            "balance_rows": balance_rows,
            "materials_summary": materials_summary,
            "layout_data": layout_data,
            "layout_zones": [z["zone"] for z in layout_data],
            "project_cards": project_cards,
            "store_form": store_form,
            "bin_form": bin_form,
            "link_form": link_form,
            "linked_project_count": len(project_cards),
            "store_count": stores_qs.count(),
            "bin_count": bins_qs.count(),
            "stock_line_count": balances_qs.filter(on_hand__gt=0).count(),
            "warehouse_stock_qty": balances_qs.aggregate(total=Sum("on_hand"))["total"] or 0,
            "warehouse_pending_requisitions": sum([item["pending_requisitions"] for item in project_cards]),
            "warehouse_returned_goods_qty": sum([item["returned_goods_qty"] for item in project_cards]),
            "recent_movements": recent_movements,
            "all_materials_json": json.dumps(all_materials),
            "alloc_store_rows": alloc_store_rows,
            "stores_bins_json": json.dumps(stores_bins_json),
            "all_warehouses": all_warehouses,
        }
    )
    return render(request, "SupplChain_MNG/warehouse_manage.html", context)


@login_required
def warehouse_quick_create_store(request, pk):
    """AJAX endpoint: create a StoreLocation attached to this warehouse and return JSON."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    _enforce_manage_access(request.user, "warehouse")
    warehouse = get_object_or_404(Warehouse, pk=pk)
    name = request.POST.get("name", "").strip()
    location_type = request.POST.get("location_type", "HQ")
    if not name:
        return JsonResponse({"error": "Name is required."}, status=400)
    if StoreLocation.objects.filter(name=name, warehouse=warehouse).exists():
        return JsonResponse({"error": f"A store named '{name}' already exists in this warehouse."}, status=400)
    store = StoreLocation.objects.create(
        name=name,
        location_type=location_type,
        warehouse=warehouse,
        is_active=True,
    )
    return JsonResponse({"id": store.id, "name": store.name})


@login_required
def warehouse_quick_create_bin(request, pk):
    """AJAX endpoint: create a StorageBin in a store of this warehouse and return JSON."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    _enforce_manage_access(request.user, "warehouse")
    warehouse = get_object_or_404(Warehouse, pk=pk)
    store_id = request.POST.get("store_location")
    bin_code = request.POST.get("bin_code", "").strip()
    zone = request.POST.get("zone", "").strip()
    aisle = request.POST.get("aisle", "").strip()
    rack = request.POST.get("rack", "").strip()
    shelf = request.POST.get("shelf", "").strip()
    description = request.POST.get("description", "").strip()
    if not store_id:
        return JsonResponse({"error": "Store is required."}, status=400)
    store = get_object_or_404(StoreLocation, pk=store_id, warehouse=warehouse)
    if bin_code and StorageBin.objects.filter(store_location=store, bin_code=bin_code).exists():
        return JsonResponse({"error": f"Bin '{bin_code}' already exists in this store."}, status=400)
    storage_bin = StorageBin.objects.create(
        store_location=store,
        bin_code=bin_code,
        zone=zone,
        aisle=aisle,
        rack=rack,
        shelf=shelf,
        description=description,
        is_active=True,
    )
    label_parts = [p for p in [storage_bin.zone, storage_bin.aisle, storage_bin.rack, storage_bin.shelf, storage_bin.bin_code] if p]
    return JsonResponse({
        "id": storage_bin.id,
        "bin_code": storage_bin.bin_code,
        "zone": storage_bin.zone,
        "aisle": storage_bin.aisle,
        "rack": storage_bin.rack,
        "shelf": storage_bin.shelf,
        "store_location_id": store.id,
        "label": " / ".join(label_parts),
    })


@login_required
def warehouse_balance_detail(request, pk, balance_id):
    """AJAX: return full detail for a single InventoryBalance (material card + stock)."""
    warehouse = get_object_or_404(Warehouse, pk=pk)
    balance = get_object_or_404(
        InventoryBalance.objects.select_related(
            "material", "material__category",
            "storage_bin", "storage_bin__store_location",
        ),
        pk=balance_id,
        storage_bin__store_location__warehouse=warehouse,
    )
    mat = balance.material
    sbin = balance.storage_bin
    # Build breadcrumb parts
    breadcrumb = []
    if sbin.store_location:
        breadcrumb.append({"label": "Store", "value": sbin.store_location.name})
    if sbin.zone:
        breadcrumb.append({"label": "Zone", "value": sbin.zone})
    if sbin.aisle:
        breadcrumb.append({"label": "Aisle", "value": sbin.aisle})
    if sbin.rack:
        breadcrumb.append({"label": "Rack", "value": sbin.rack})
    if sbin.shelf:
        breadcrumb.append({"label": "Shelf", "value": sbin.shelf})
    breadcrumb.append({"label": "Bin", "value": sbin.bin_code})

    photo_url = mat.photo.url if mat.photo else None
    status = "in_stock"
    if balance.on_hand <= 0:
        status = "out_of_stock"
    elif balance.min_required > 0 and balance.on_hand <= balance.min_required:
        status = "low_stock"

    return JsonResponse({
        "balance_id": balance.pk,
        "material_id": mat.pk,
        "material_name": mat.name,
        "material_code": mat.code_number,
        "category": mat.category.name if mat.category else "",
        "unit": mat.unit,
        "measurement_unit": mat.get_measurement_unit_display(),
        "is_consumable": mat.is_consumable,
        "photo_url": photo_url,
        "on_hand": str(balance.on_hand),
        "reserved": str(balance.reserved),
        "available": str(balance.on_hand - balance.reserved),
        "min_required": str(balance.min_required),
        "status": status,
        "breadcrumb": breadcrumb,
        "material_edit_url": f"/workspace/materials/{mat.pk}/",
    })


@login_required
def warehouse_balance_update(request, pk, balance_id):
    """AJAX POST: update on_hand and/or min_required for a balance record."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    _enforce_manage_access(request.user, "warehouse")
    warehouse = get_object_or_404(Warehouse, pk=pk)
    balance = get_object_or_404(
        InventoryBalance,
        pk=balance_id,
        storage_bin__store_location__warehouse=warehouse,
    )
    errors = {}
    try:
        new_on_hand = Decimal(request.POST.get("on_hand", str(balance.on_hand)))
        if new_on_hand < 0:
            errors["on_hand"] = "Cannot be negative."
    except Exception:
        errors["on_hand"] = "Invalid number."
    try:
        new_min = Decimal(request.POST.get("min_required", str(balance.min_required)))
        if new_min < 0:
            errors["min_required"] = "Cannot be negative."
    except Exception:
        errors["min_required"] = "Invalid number."
    if errors:
        return JsonResponse({"error": errors}, status=400)

    balance.on_hand = new_on_hand
    balance.min_required = new_min
    balance.save(update_fields=["on_hand", "min_required", "updated_at"])

    status = "in_stock"
    if balance.on_hand <= 0:
        status = "out_of_stock"
    elif balance.min_required > 0 and balance.on_hand <= balance.min_required:
        status = "low_stock"

    return JsonResponse({
        "on_hand": str(balance.on_hand),
        "reserved": str(balance.reserved),
        "available": str(balance.on_hand - balance.reserved),
        "min_required": str(balance.min_required),
        "status": status,
    })


@login_required
def material_returns_view(request):
    context = _base_context(request, "returns")
    context["rows"] = context["returns"].order_by("-date_returned")
    return render(request, "SupplChain_MNG/material_returns.html", context)



@login_required
def goods_received_view(request):
    context = _base_context(request, "goods_received")
    project_context = _project_context_for_list(request)

    if request.method == "POST":
        _enforce_manage_access(request.user, "goods_received")
        receipt_id = request.POST.get("receipt_id")
        action = request.POST.get("action")
        receipt = get_object_or_404(GoodsReceipt.objects.select_related("destination_store"), pk=receipt_id)
        _enforce_store_manage_scope(request.user, receipt.destination_store_id)

        try:
            with transaction.atomic():
                if action == "post" and receipt.status == "DRAFT":
                    if receipt.stock_posted:
                        raise ValidationError("This goods receipt has already been posted to stock.")

                    destination_bin = receipt.destination_bin
                    if destination_bin is None:
                        raise ValidationError("Put-away BIN is required before posting goods receipt.")

                    items = list(receipt.items.select_related("material"))
                    if not items:
                        raise ValidationError("Goods receipt has no items.")

                    for line in items:
                        if line.quantity <= 0:
                            continue
                        return_tag = "Returnable" if line.is_returnable else "Non-returnable"
                        InventoryMovement.objects.create(
                            movement_type="RECEIPT",
                            material=line.material,
                            quantity=line.quantity,
                            to_store=receipt.destination_store,
                            to_bin=destination_bin,
                            reference_type="GOODS_RECEIVED",
                            reference_number=receipt.receipt_number,
                            notes=f"{return_tag}. {line.description}".strip(),
                            created_by=request.user,
                        )

                    receipt.status = "POSTED"
                    receipt.stock_posted = True
                    receipt.posted_by = request.user
                    receipt.posted_at = timezone.now()
                    receipt.save(update_fields=["status", "stock_posted", "posted_by", "posted_at"])
                    _log_action(request, "UPDATE", "GoodsReceipt", receipt.id, f"Posted goods receipt {receipt.receipt_number}")
                    messages.success(request, f"Goods receipt {receipt.receipt_number} posted to stock.")
                else:
                    messages.warning(request, "Goods receipt action is not valid for current status.")
        except ValidationError as exc:
            messages.error(request, str(exc))

        if project_context:
            return redirect(f"{request.path}?project={project_context.id}")
        return redirect("goods_received")

    rows = _filter_by_store_scope(
        GoodsReceipt.objects.select_related("destination_store", "related_delivery_note").prefetch_related("items").order_by("-created_at"),
        request.user,
        "destination_store_id",
    )
    if project_context:
        project_store_ids = list(StoreLocation.objects.filter(project=project_context).values_list("id", flat=True))
        rows = rows.filter(destination_store_id__in=project_store_ids)
    if context["filters"]["name"]:
        rows = rows.filter(
            Q(receipt_number__icontains=context["filters"]["name"]) |
            Q(destination_store__name__icontains=context["filters"]["name"]) |
            Q(source_reference__icontains=context["filters"]["name"])
        )

    rows = list(rows)
    for item in rows:
        lines = list(item.items.all())
        item.item_count = len(lines)
        item.total_quantity = sum([line.quantity for line in lines], Decimal("0.00"))

    context["rows"] = rows
    context["project_context"] = project_context
    return render(request, "SupplChain_MNG/goods_received.html", context)


@login_required
def goods_received_create_view(request):
    _enforce_manage_access(request.user, "goods_received")
    receipt = GoodsReceipt(created_by=request.user)
    form = GoodsReceiptForm(request.POST or None, instance=receipt)
    formset = GoodsReceiptItemFormSet(request.POST or None, instance=receipt, prefix="items")

    project, project_stores_qs, project_store_ids = _project_store_context(request)
    selected_store_param = (request.GET.get("store") or "").strip()
    selected_store_qs = StoreLocation.objects.filter(pk=selected_store_param) if selected_store_param else StoreLocation.objects.none()
    selected_store_qs = _filter_by_store_scope(selected_store_qs, request.user, "id")
    selected_store = selected_store_qs.first() if selected_store_param else None
    if project:
        form.fields["destination_store"].queryset = project_stores_qs
        form.fields["destination_bin"].queryset = StorageBin.objects.filter(
            store_location_id__in=project_store_ids,
            is_active=True,
        ).order_by("store_location__name", "bin_code")
        if request.method == "GET" and len(project_store_ids) == 1:
            form.fields["destination_store"].initial = project_store_ids[0]
            form.fields["destination_bin"].queryset = StorageBin.objects.filter(
                store_location_id=project_store_ids[0],
                is_active=True,
            ).order_by("bin_code")

    if selected_store:
        form.fields["destination_store"].queryset = StoreLocation.objects.filter(pk=selected_store.pk)
        form.fields["destination_store"].initial = selected_store.pk
        form.fields["destination_bin"].queryset = StorageBin.objects.filter(
            store_location=selected_store,
            is_active=True,
        ).order_by("bin_code")

    selected_store_id = (request.POST.get("destination_store") if request.method == "POST" else form.initial.get("destination_store"))
    if selected_store_id:
        form.fields["destination_bin"].queryset = StorageBin.objects.filter(
            store_location_id=selected_store_id,
            is_active=True,
        ).order_by("bin_code")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        receipt = form.save(commit=False)
        _enforce_store_manage_scope(request.user, receipt.destination_store_id)
        receipt.created_by = request.user
        receipt.save()
        formset.instance = receipt
        formset.save()
        _log_action(request, "CREATE", "GoodsReceipt", receipt.id, f"Created goods receipt {receipt.receipt_number}")
        return redirect("project_manage", pk=project.id) if project else redirect("goods_received")

    context = _base_context(request, "goods_received")
    context.update({
        "form": form,
        "formset": formset,
        "title": "Create Goods Received",
        "is_edit": False,
        "project_context": project,
    })
    return render(request, "SupplChain_MNG/goods_received_form.html", context)


@login_required
def goods_received_update_view(request, pk):
    _enforce_manage_access(request.user, "goods_received")
    receipt = get_object_or_404(GoodsReceipt, pk=pk)
    _enforce_store_manage_scope(request.user, receipt.destination_store_id)
    if receipt.status != "DRAFT":
        messages.error(request, "Only draft goods receipts can be edited.")
        return redirect("goods_received")

    form = GoodsReceiptForm(request.POST or None, instance=receipt)
    formset = GoodsReceiptItemFormSet(request.POST or None, instance=receipt, prefix="items")

    selected_store_id = request.POST.get("destination_store") if request.method == "POST" else receipt.destination_store_id
    if selected_store_id:
        form.fields["destination_bin"].queryset = StorageBin.objects.filter(
            store_location_id=selected_store_id,
            is_active=True,
        ).order_by("bin_code")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        receipt = form.save()
        formset.save()
        _log_action(request, "UPDATE", "GoodsReceipt", receipt.id, f"Updated goods receipt {receipt.receipt_number}")
        return redirect("goods_received")

    context = _base_context(request, "goods_received")
    context.update({"form": form, "formset": formset, "title": "Edit Goods Received", "is_edit": True, "receipt": receipt})
    return render(request, "SupplChain_MNG/goods_received_form.html", context)


@login_required
def goods_received_delete_view(request, pk):
    _enforce_manage_access(request.user, "goods_received")
    receipt = get_object_or_404(GoodsReceipt, pk=pk)
    _enforce_store_manage_scope(request.user, receipt.destination_store_id)
    if receipt.status != "DRAFT":
        messages.error(request, "Only draft goods receipts can be deleted.")
        return redirect("goods_received")

    if request.method == "POST":
        _log_action(request, "DELETE", "GoodsReceipt", receipt.id, f"Deleted goods receipt {receipt.receipt_number}")
        receipt.delete()
        return redirect("goods_received")

    context = _base_context(request, "goods_received")
    context.update({"title": "Delete Goods Received", "object": receipt, "cancel_route": "goods_received"})
    return render(request, "SupplChain_MNG/crud_confirm_delete.html", context)


@login_required
def goods_issue_view(request):
    context = _base_context(request, "goods_issue")
    project_context = _project_context_for_list(request)

    if request.method == "POST":
        _enforce_manage_access(request.user, "goods_issue")
        issue_id = request.POST.get("issue_id")
        action = request.POST.get("action")
        issue = get_object_or_404(GoodsIssue.objects.select_related("source_store", "source_bin"), pk=issue_id)
        _enforce_store_manage_scope(request.user, issue.source_store_id)

        try:
            with transaction.atomic():
                if action == "post" and issue.status == "DRAFT":
                    if issue.stock_posted:
                        raise ValidationError("This goods issue has already been posted.")

                    source_bin = issue.source_bin
                    if source_bin is None:
                        source_bin = (
                            StorageBin.objects.filter(store_location=issue.source_store, is_active=True)
                            .order_by("bin_code")
                            .first()
                        )
                    if source_bin is None:
                        raise ValidationError("No active BIN found for selected source store.")

                    items = list(issue.items.select_related("material"))
                    if not items:
                        raise ValidationError("Goods issue has no items.")

                    for line in items:
                        if line.quantity <= 0:
                            continue
                        return_tag = "Returnable" if line.is_returnable else "Non-returnable"
                        InventoryMovement.objects.create(
                            movement_type="ISSUE",
                            material=line.material,
                            quantity=line.quantity,
                            from_store=issue.source_store,
                            from_bin=source_bin,
                            reference_type="GOODS_ISSUE",
                            reference_number=issue.issue_number,
                            notes=f"{return_tag}. {line.description}".strip(),
                            created_by=request.user,
                        )

                    issue.status = "POSTED"
                    issue.stock_posted = True
                    issue.posted_by = request.user
                    issue.posted_at = timezone.now()
                    issue.save(update_fields=["status", "stock_posted", "posted_by", "posted_at"])
                    _log_action(request, "UPDATE", "GoodsIssue", issue.id, f"Posted goods issue {issue.issue_number}")
                    messages.success(request, f"Goods issue {issue.issue_number} posted.")
                else:
                    messages.warning(request, "Goods issue action is not valid for current status.")
        except ValidationError as exc:
            messages.error(request, str(exc))

        if project_context:
            return redirect(f"{request.path}?project={project_context.id}")
        return redirect("goods_issue")

    rows = _filter_by_store_scope(
        GoodsIssue.objects.select_related("source_store").prefetch_related("items").order_by("-created_at"),
        request.user,
        "source_store_id",
    )
    if project_context:
        project_store_ids = list(StoreLocation.objects.filter(project=project_context).values_list("id", flat=True))
        rows = rows.filter(source_store_id__in=project_store_ids)
    if context["filters"]["name"]:
        rows = rows.filter(
            Q(issue_number__icontains=context["filters"]["name"]) |
            Q(source_store__name__icontains=context["filters"]["name"]) |
            Q(department__icontains=context["filters"]["name"]) |
            Q(issued_to__icontains=context["filters"]["name"]) 
        )

    rows = list(rows)
    for item in rows:
        lines = list(item.items.all())
        item.item_count = len(lines)
        item.total_quantity = sum([line.quantity for line in lines], Decimal("0.00"))
        item.returnable_count = len([line for line in lines if line.is_returnable])

    context["rows"] = rows
    context["project_context"] = project_context
    return render(request, "SupplChain_MNG/goods_issue.html", context)


@login_required
def goods_issue_create_view(request):
    _enforce_manage_access(request.user, "goods_issue")
    issue = GoodsIssue(created_by=request.user)
    form = GoodsIssueForm(request.POST or None, instance=issue)
    formset = GoodsIssueItemFormSet(request.POST or None, instance=issue, prefix="items")

    project, project_stores_qs, project_store_ids = _project_store_context(request)
    if project:
        form.fields["source_store"].queryset = project_stores_qs
        form.fields["source_bin"].queryset = StorageBin.objects.filter(store_location_id__in=project_store_ids).order_by(
            "store_location__name", "bin_code"
        )
        if request.method == "GET" and len(project_store_ids) == 1:
            form.fields["source_store"].initial = project_store_ids[0]

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        issue = form.save(commit=False)
        _enforce_store_manage_scope(request.user, issue.source_store_id)
        issue.created_by = request.user
        issue.save()
        formset.instance = issue
        formset.save()
        _log_action(request, "CREATE", "GoodsIssue", issue.id, f"Created goods issue {issue.issue_number}")
        return redirect("project_manage", pk=project.id) if project else redirect("goods_issue")

    context = _base_context(request, "goods_issue")
    context.update({
        "form": form,
        "formset": formset,
        "title": "Create Goods Issue",
        "is_edit": False,
        "project_context": project,
    })
    return render(request, "SupplChain_MNG/goods_issue_form.html", context)


@login_required
def goods_issue_update_view(request, pk):
    _enforce_manage_access(request.user, "goods_issue")
    issue = get_object_or_404(GoodsIssue, pk=pk)
    _enforce_store_manage_scope(request.user, issue.source_store_id)
    if issue.status != "DRAFT":
        messages.error(request, "Only draft goods issues can be edited.")
        return redirect("goods_issue")

    form = GoodsIssueForm(request.POST or None, instance=issue)
    formset = GoodsIssueItemFormSet(request.POST or None, instance=issue, prefix="items")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        issue = form.save()
        formset.save()
        _log_action(request, "UPDATE", "GoodsIssue", issue.id, f"Updated goods issue {issue.issue_number}")
        return redirect("goods_issue")

    context = _base_context(request, "goods_issue")
    context.update({"form": form, "formset": formset, "title": "Edit Goods Issue", "is_edit": True, "issue": issue})
    return render(request, "SupplChain_MNG/goods_issue_form.html", context)


@login_required
def goods_issue_delete_view(request, pk):
    _enforce_manage_access(request.user, "goods_issue")
    issue = get_object_or_404(GoodsIssue, pk=pk)
    _enforce_store_manage_scope(request.user, issue.source_store_id)
    if issue.status != "DRAFT":
        messages.error(request, "Only draft goods issues can be deleted.")
        return redirect("goods_issue")

    if request.method == "POST":
        _log_action(request, "DELETE", "GoodsIssue", issue.id, f"Deleted goods issue {issue.issue_number}")
        issue.delete()
        return redirect("goods_issue")

    context = _base_context(request, "goods_issue")
    context.update({"title": "Delete Goods Issue", "object": issue, "cancel_route": "goods_issue"})
    return render(request, "SupplChain_MNG/crud_confirm_delete.html", context)


@login_required
def goods_returns_view(request):
    context = _base_context(request, "goods_returns")
    project_context = _project_context_for_list(request)

    if request.method == "POST":
        _enforce_manage_access(request.user, "goods_returns")
        ret_id = request.POST.get("return_id")
        action = request.POST.get("action")
        goods_return = get_object_or_404(GoodsReturn.objects.select_related("destination_store", "from_store"), pk=ret_id)
        _enforce_store_manage_scope(request.user, goods_return.destination_store_id)

        try:
            with transaction.atomic():
                if action == "post" and goods_return.status == "DRAFT":
                    if goods_return.stock_posted:
                        raise ValidationError("This goods return has already been posted.")

                    destination_bin = (
                        StorageBin.objects.filter(store_location=goods_return.destination_store, is_active=True)
                        .order_by("bin_code")
                        .first()
                    )
                    if destination_bin is None:
                        destination_bin = StorageBin.objects.create(store_location=goods_return.destination_store, bin_code="")

                    source_bin = None
                    if goods_return.from_store:
                        source_bin = (
                            StorageBin.objects.filter(store_location=goods_return.from_store, is_active=True)
                            .order_by("bin_code")
                            .first()
                        )

                    items = list(goods_return.items.select_related("material"))
                    if not items:
                        raise ValidationError("Goods return has no items.")

                    for line in items:
                        if line.quantity <= 0:
                            continue
                        InventoryMovement.objects.create(
                            movement_type="RETURN",
                            material=line.material,
                            quantity=line.quantity,
                            from_store=goods_return.from_store,
                            from_bin=source_bin,
                            to_store=goods_return.destination_store,
                            to_bin=destination_bin,
                            reference_type="GOODS_RETURN",
                            reference_number=goods_return.return_number,
                            notes=f"Condition: {line.get_condition_display()}. {line.notes}".strip(),
                            created_by=request.user,
                        )

                    goods_return.status = "POSTED"
                    goods_return.stock_posted = True
                    goods_return.posted_by = request.user
                    goods_return.posted_at = timezone.now()
                    goods_return.save(update_fields=["status", "stock_posted", "posted_by", "posted_at"])
                    _log_action(request, "UPDATE", "GoodsReturn", goods_return.id, f"Posted goods return {goods_return.return_number}")
                    messages.success(request, f"Goods return {goods_return.return_number} posted.")
                else:
                    messages.warning(request, "Goods return action is not valid for current status.")
        except ValidationError as exc:
            messages.error(request, str(exc))

        if project_context:
            return redirect(f"{request.path}?project={project_context.id}")
        return redirect("goods_returns")

    rows = _filter_by_store_scope(
        GoodsReturn.objects.select_related("from_store", "destination_store", "related_goods_issue").prefetch_related("items").order_by("-created_at"),
        request.user,
        "destination_store_id",
    )
    if project_context:
        project_store_ids = list(StoreLocation.objects.filter(project=project_context).values_list("id", flat=True))
        rows = rows.filter(destination_store_id__in=project_store_ids)
    if context["filters"]["name"]:
        rows = rows.filter(
            Q(return_number__icontains=context["filters"]["name"]) |
            Q(destination_store__name__icontains=context["filters"]["name"]) |
            Q(from_store__name__icontains=context["filters"]["name"]) |
            Q(returned_by__icontains=context["filters"]["name"]) 
        )

    rows = list(rows)
    for item in rows:
        lines = list(item.items.all())
        item.item_count = len(lines)
        item.total_quantity = sum([line.quantity for line in lines], Decimal("0.00"))
        item.scrap_count = len([line for line in lines if line.condition == "SCRAP"])

    context["rows"] = rows
    context["project_context"] = project_context
    return render(request, "SupplChain_MNG/goods_returns.html", context)


@login_required
def goods_returns_create_view(request):
    _enforce_manage_access(request.user, "goods_returns")
    goods_return = GoodsReturn(created_by=request.user)
    form = GoodsReturnForm(request.POST or None, instance=goods_return)
    formset = GoodsReturnItemFormSet(request.POST or None, instance=goods_return, prefix="items")

    project, project_stores_qs, project_store_ids = _project_store_context(request)
    if project:
        form.fields["destination_store"].queryset = project_stores_qs
        form.fields["from_store"].queryset = project_stores_qs
        if request.method == "GET" and len(project_store_ids) == 1:
            form.fields["destination_store"].initial = project_store_ids[0]

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        goods_return = form.save(commit=False)
        _enforce_store_manage_scope(request.user, goods_return.destination_store_id)
        goods_return.created_by = request.user
        goods_return.save()
        formset.instance = goods_return
        formset.save()
        _log_action(request, "CREATE", "GoodsReturn", goods_return.id, f"Created goods return {goods_return.return_number}")
        return redirect("project_manage", pk=project.id) if project else redirect("goods_returns")

    context = _base_context(request, "goods_returns")
    context.update({
        "form": form,
        "formset": formset,
        "title": "Create Goods Return",
        "is_edit": False,
        "project_context": project,
    })
    return render(request, "SupplChain_MNG/goods_returns_form.html", context)


@login_required
def goods_returns_update_view(request, pk):
    _enforce_manage_access(request.user, "goods_returns")
    goods_return = get_object_or_404(GoodsReturn, pk=pk)
    _enforce_store_manage_scope(request.user, goods_return.destination_store_id)
    if goods_return.status != "DRAFT":
        messages.error(request, "Only draft goods returns can be edited.")
        return redirect("goods_returns")

    form = GoodsReturnForm(request.POST or None, instance=goods_return)
    formset = GoodsReturnItemFormSet(request.POST or None, instance=goods_return, prefix="items")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        goods_return = form.save()
        formset.save()
        _log_action(request, "UPDATE", "GoodsReturn", goods_return.id, f"Updated goods return {goods_return.return_number}")
        return redirect("goods_returns")

    context = _base_context(request, "goods_returns")
    context.update({"form": form, "formset": formset, "title": "Edit Goods Return", "is_edit": True, "goods_return": goods_return})
    return render(request, "SupplChain_MNG/goods_returns_form.html", context)


@login_required
def goods_returns_delete_view(request, pk):
    _enforce_manage_access(request.user, "goods_returns")
    goods_return = get_object_or_404(GoodsReturn, pk=pk)
    _enforce_store_manage_scope(request.user, goods_return.destination_store_id)
    if goods_return.status != "DRAFT":
        messages.error(request, "Only draft goods returns can be deleted.")
        return redirect("goods_returns")

    if request.method == "POST":
        _log_action(request, "DELETE", "GoodsReturn", goods_return.id, f"Deleted goods return {goods_return.return_number}")
        goods_return.delete()
        return redirect("goods_returns")

    context = _base_context(request, "goods_returns")
    context.update({"title": "Delete Goods Return", "object": goods_return, "cancel_route": "goods_returns"})
    return render(request, "SupplChain_MNG/crud_confirm_delete.html", context)


@login_required
def ppe_issues_view(request):
    context = _base_context(request, "ppe")
    project_context = _project_context_for_list(request)

    if request.method == "POST":
        _enforce_manage_access(request.user, "ppe")
        ppe_id = request.POST.get("ppe_id")
        action = request.POST.get("action")
        ppe_issue = get_object_or_404(PPEIssue.objects.select_related("store_location", "source_bin"), pk=ppe_id)
        _enforce_store_manage_scope(request.user, ppe_issue.store_location_id)

        try:
            with transaction.atomic():
                if action == "post" and ppe_issue.status == "DRAFT":
                    if ppe_issue.stock_posted:
                        raise ValidationError("This PPE issue has already been posted.")

                    source_bin = ppe_issue.source_bin
                    if source_bin is None:
                        source_bin = (
                            StorageBin.objects.filter(store_location=ppe_issue.store_location, is_active=True)
                            .order_by("bin_code")
                            .first()
                        )
                    if source_bin is None:
                        raise ValidationError("No active BIN found for selected PPE store.")

                    lines = list(ppe_issue.items.select_related("material"))
                    if not lines:
                        raise ValidationError("PPE issue has no items.")

                    for line in lines:
                        if line.quantity <= 0:
                            continue
                        InventoryMovement.objects.create(
                            movement_type="ISSUE",
                            material=line.material,
                            quantity=line.quantity,
                            from_store=ppe_issue.store_location,
                            from_bin=source_bin,
                            reference_type="PPE_ISSUE",
                            reference_number=ppe_issue.issue_number,
                            notes=f"PPE {ppe_issue.get_issue_type_display()} for {ppe_issue.employee_name}. {line.size_spec}".strip(),
                            created_by=request.user,
                        )

                    ppe_issue.status = "POSTED"
                    ppe_issue.stock_posted = True
                    ppe_issue.posted_by = request.user
                    ppe_issue.posted_at = timezone.now()
                    ppe_issue.save(update_fields=["status", "stock_posted", "posted_by", "posted_at"])
                    _log_action(request, "UPDATE", "PPEIssue", ppe_issue.id, f"Posted PPE issue {ppe_issue.issue_number}")
                    messages.success(request, f"PPE issue {ppe_issue.issue_number} posted.")
                else:
                    messages.warning(request, "PPE action is not valid for current status.")
        except ValidationError as exc:
            messages.error(request, str(exc))

        if project_context:
            return redirect(f"{request.path}?project={project_context.id}")
        return redirect("ppe_issues")

    rows = _filter_by_store_scope(
        PPEIssue.objects.select_related("store_location").prefetch_related("items").order_by("-created_at"),
        request.user,
        "store_location_id",
    )
    if project_context:
        project_store_ids = list(StoreLocation.objects.filter(project=project_context).values_list("id", flat=True))
        rows = rows.filter(store_location_id__in=project_store_ids)
    if context["filters"]["name"]:
        rows = rows.filter(
            Q(issue_number__icontains=context["filters"]["name"]) |
            Q(employee_name__icontains=context["filters"]["name"]) |
            Q(employee_number__icontains=context["filters"]["name"]) |
            Q(store_location__name__icontains=context["filters"]["name"]) 
        )

    rows = list(rows)
    for item in rows:
        lines = list(item.items.all())
        item.item_count = len(lines)
        item.total_quantity = sum([line.quantity for line in lines], Decimal("0.00"))

    context["rows"] = rows
    context["project_context"] = project_context
    return render(request, "SupplChain_MNG/ppe_issues.html", context)


@login_required
def ppe_issues_create_view(request):
    _enforce_manage_access(request.user, "ppe")
    ppe_issue = PPEIssue(created_by=request.user)
    form = PPEIssueForm(request.POST or None, instance=ppe_issue)
    formset = PPEIssueItemFormSet(request.POST or None, instance=ppe_issue, prefix="items")

    project, project_stores_qs, project_store_ids = _project_store_context(request)
    if project:
        form.fields["store_location"].queryset = project_stores_qs
        form.fields["source_bin"].queryset = StorageBin.objects.filter(store_location_id__in=project_store_ids).order_by(
            "store_location__name", "bin_code"
        )
        if request.method == "GET" and len(project_store_ids) == 1:
            form.fields["store_location"].initial = project_store_ids[0]

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        ppe_issue = form.save(commit=False)
        _enforce_store_manage_scope(request.user, ppe_issue.store_location_id)
        ppe_issue.created_by = request.user
        ppe_issue.save()
        formset.instance = ppe_issue
        formset.save()
        _log_action(request, "CREATE", "PPEIssue", ppe_issue.id, f"Created PPE issue {ppe_issue.issue_number}")
        return redirect("project_manage", pk=project.id) if project else redirect("ppe_issues")

    context = _base_context(request, "ppe")
    context.update({
        "form": form,
        "formset": formset,
        "title": "Create PPE Issue",
        "is_edit": False,
        "project_context": project,
    })
    return render(request, "SupplChain_MNG/ppe_issues_form.html", context)


@login_required
def ppe_issues_update_view(request, pk):
    _enforce_manage_access(request.user, "ppe")
    ppe_issue = get_object_or_404(PPEIssue, pk=pk)
    _enforce_store_manage_scope(request.user, ppe_issue.store_location_id)
    if ppe_issue.status != "DRAFT":
        messages.error(request, "Only draft PPE issues can be edited.")
        return redirect("ppe_issues")

    form = PPEIssueForm(request.POST or None, instance=ppe_issue)
    formset = PPEIssueItemFormSet(request.POST or None, instance=ppe_issue, prefix="items")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        ppe_issue = form.save()
        formset.save()
        _log_action(request, "UPDATE", "PPEIssue", ppe_issue.id, f"Updated PPE issue {ppe_issue.issue_number}")
        return redirect("ppe_issues")

    context = _base_context(request, "ppe")
    context.update({"form": form, "formset": formset, "title": "Edit PPE Issue", "is_edit": True, "ppe_issue": ppe_issue})
    return render(request, "SupplChain_MNG/ppe_issues_form.html", context)


@login_required
def ppe_issues_delete_view(request, pk):
    _enforce_manage_access(request.user, "ppe")
    ppe_issue = get_object_or_404(PPEIssue, pk=pk)
    _enforce_store_manage_scope(request.user, ppe_issue.store_location_id)
    if ppe_issue.status != "DRAFT":
        messages.error(request, "Only draft PPE issues can be deleted.")
        return redirect("ppe_issues")

    if request.method == "POST":
        _log_action(request, "DELETE", "PPEIssue", ppe_issue.id, f"Deleted PPE issue {ppe_issue.issue_number}")
        ppe_issue.delete()
        return redirect("ppe_issues")

    context = _base_context(request, "ppe")
    context.update({"title": "Delete PPE Issue", "object": ppe_issue, "cancel_route": "ppe_issues"})
    return render(request, "SupplChain_MNG/crud_confirm_delete.html", context)


@login_required
def ops_overview_view(request):
    context = _base_context(request, "overview")
    scoped_ids = _scoped_store_ids(request.user)

    store_qs = StoreLocation.objects.filter(is_active=True)
    if scoped_ids is not None:
        store_qs = store_qs.filter(id__in=scoped_ids)

    balance_qs = InventoryBalance.objects.select_related("storage_bin", "storage_bin__store_location")
    if scoped_ids is not None:
        balance_qs = balance_qs.filter(storage_bin__store_location_id__in=scoped_ids)

    goods_received_qs = GoodsReceipt.objects.all()
    goods_issue_qs = GoodsIssue.objects.all()
    goods_return_qs = GoodsReturn.objects.all()
    ppe_qs = PPEIssue.objects.all()
    if scoped_ids is not None:
        goods_received_qs = goods_received_qs.filter(destination_store_id__in=scoped_ids)
        goods_issue_qs = goods_issue_qs.filter(source_store_id__in=scoped_ids)
        goods_return_qs = goods_return_qs.filter(destination_store_id__in=scoped_ids)
        ppe_qs = ppe_qs.filter(store_location_id__in=scoped_ids)

    scoped_project_ids = set(
        store_qs.exclude(project_id__isnull=True).values_list("project_id", flat=True)
    )
    delivery_qs = DeliveryNote.objects.filter(status="DISPATCHED")
    requisition_qs = Requisition.objects.filter(status__in=["SUBMITTED", "VALIDATED"])
    equipment_qs = Equipment.objects.all()
    mobile_qs = MobileEquipment.objects.all()
    if scoped_ids is not None:
        delivery_qs = delivery_qs.filter(source_requisition__project_id__in=scoped_project_ids)
        requisition_qs = requisition_qs.filter(project_id__in=scoped_project_ids)
        equipment_qs = equipment_qs.filter(store_location_id__in=scoped_ids)
        mobile_qs = mobile_qs.filter(store_location_id__in=scoped_ids)

    context.update(
        {
            "active_store_count": store_qs.count(),
            "stock_line_count": balance_qs.filter(on_hand__gt=0).count(),
            "reserved_total": balance_qs.aggregate(total=Sum("reserved"))["total"] or 0,
            "goods_received_posted": goods_received_qs.filter(status="POSTED").count(),
            "goods_issue_posted": goods_issue_qs.filter(status="POSTED").count(),
            "goods_returns_posted": goods_return_qs.filter(status="POSTED").count(),
            "ppe_issues_posted": ppe_qs.filter(status="POSTED").count(),
            "delivery_dispatched": delivery_qs.count(),
            "pending_requisitions": requisition_qs.count(),
            "equipment_linked_count": equipment_qs.exclude(store_location_id__isnull=True).count(),
            "fleet_linked_count": mobile_qs.exclude(store_location_id__isnull=True).count(),
        }
    )
    return render(request, "SupplChain_MNG/ops_overview.html", context)


@login_required
def stock_transactions_view(request):
    context = _base_context(request, "transactions")
    context["rows"] = context["transactions"].order_by("-date")
    return render(request, "SupplChain_MNG/stock_transactions.html", context)


@login_required
def categories_view(request):
    context = _base_context(request, "categories")
    context["rows"] = Category.objects.annotate(subcategory_count=Count("subcategory")).order_by("name")
    context["sub_rows"] = SubCategory.objects.select_related("category").order_by("category__name", "name")
    return render(request, "SupplChain_MNG/categories.html", context)


@login_required
def equipment_management_view(request):
    context = _base_context(request, "equipment")
    rows = _filter_by_store_scope(
        Equipment.objects.select_related("subcategory", "project", "subcategory__category", "store_location").order_by("name"),
        request.user,
        "store_location_id",
    )
    if context["filters"]["name"]:
        rows = rows.filter(name__icontains=context["filters"]["name"])
    if context["filters"]["category"]:
        rows = rows.filter(subcategory__category_id=context["filters"]["category"])

    rows = list(rows)
    for item in rows:
        item.service_due_meta = _due_meta(item.service_due_date)

    context.update(
        {
            "rows": rows,
            "active_equipment_count": len([row for row in rows if row.is_active]),
            "maintenance_equipment_count": len([row for row in rows if row.status == "MAINTENANCE"]),
            "broken_equipment_count": len([row for row in rows if row.status == "BROKEN"]),
        }
    )
    return render(request, "SupplChain_MNG/equipment_management.html", context)


@login_required
def equipment_detail_view(request, pk):
    context = _base_context(request, "equipment")
    equipment_qs = _filter_by_store_scope(
        Equipment.objects.select_related("subcategory", "subcategory__category", "project", "store_location"),
        request.user,
        "store_location_id",
    )
    equipment = get_object_or_404(
        equipment_qs,
        pk=pk,
    )
    context.update(
        {
            "equipment": equipment,
            "service_due_meta": _due_meta(equipment.service_due_date),
            "linked_materials": Material.objects.filter(equipment=equipment).select_related("category").order_by("name"),
            "recent_related_transactions": StockTransaction.objects.filter(material__equipment=equipment).select_related("material", "performed_by").order_by("-date")[:12],
        }
    )
    return render(request, "SupplChain_MNG/equipment_detail.html", context)


@login_required
def delivery_notes_view(request):
    def _deduct_hq_for_note(note, actor):
        items = list(note.items.select_related("material").all())
        if not items:
            raise ValidationError("Delivery note has no items to dispatch.")

        for item in items:
            remaining = Decimal(str(item.quantity))
            if remaining <= 0:
                continue

            if note.source_requisition_id and note.source_requisition.material_id == item.material_id:
                reservation_lines = list(
                    note.source_requisition.reservations.select_related(
                        "inventory_balance",
                        "inventory_balance__storage_bin",
                        "inventory_balance__storage_bin__store_location",
                    ).order_by("created_at")
                )
                for line in reservation_lines:
                    if remaining <= 0:
                        break
                    take = min(remaining, line.quantity)
                    bal = line.inventory_balance

                    InventoryMovement.objects.create(
                        movement_type="ISSUE",
                        material=item.material,
                        quantity=take,
                        from_store=bal.storage_bin.store_location,
                        from_bin=bal.storage_bin,
                        reference_type="DELIVERY_NOTE",
                        reference_number=note.note_number,
                        notes=f"Dispatch against requisition {note.source_requisition_id}",
                        created_by=actor,
                    )

                    bal.reserved = max(Decimal("0.00"), bal.reserved - take)
                    bal.save(update_fields=["reserved", "updated_at"])

                    line.quantity -= take
                    if line.quantity <= 0:
                        line.delete()
                    else:
                        line.save(update_fields=["quantity"])
                    remaining -= take

            if remaining > 0:
                balances = list(
                    InventoryBalance.objects.select_related("storage_bin", "storage_bin__store_location")
                    .filter(material=item.material, storage_bin__store_location__location_type="HQ")
                    .order_by("storage_bin__store_location__name", "storage_bin__bin_code")
                )
                for bal in balances:
                    if remaining <= 0:
                        break
                    available = bal.on_hand - bal.reserved
                    if available <= 0:
                        continue
                    take = min(available, remaining)
                    InventoryMovement.objects.create(
                        movement_type="ISSUE",
                        material=item.material,
                        quantity=take,
                        from_store=bal.storage_bin.store_location,
                        from_bin=bal.storage_bin,
                        reference_type="DELIVERY_NOTE",
                        reference_number=note.note_number,
                        notes="Dispatch deduction from HQ stock",
                        created_by=actor,
                    )
                    remaining -= take

            if remaining > 0:
                raise ValidationError(
                    f"Insufficient available HQ stock for {item.material.name}. Short by {remaining}."
                )

        if note.source_requisition_id:
            remaining_reserved = (
                note.source_requisition.reservations.aggregate(total=Sum("quantity"))["total"] or Decimal("0.00")
            )
            note.source_requisition.reserved_quantity = remaining_reserved
            note.source_requisition.save(update_fields=["reserved_quantity", "fulfilled"])

    def _receive_into_site_store(note, actor):
        if note.status != "DISPATCHED":
            raise ValidationError("Only dispatched delivery notes can be received.")

        destination_store = None
        if note.source_requisition_id and note.source_requisition.project_id:
            destination_store = (
                StoreLocation.objects.filter(
                    project=note.source_requisition.project,
                    location_type="SITE",
                    is_active=True,
                )
                .order_by("name")
                .first()
            )

        if destination_store is None and note.to_location:
            destination_store = (
                StoreLocation.objects.filter(
                    location_type="SITE",
                    is_active=True,
                    name__icontains=note.to_location,
                )
                .order_by("name")
                .first()
            )

        if destination_store is None:
            raise ValidationError(
                "No active site store found for this delivery note. Configure a SITE store for the project or matching destination name first."
            )

        destination_bin = (
            StorageBin.objects.filter(store_location=destination_store, is_active=True)
            .order_by("bin_code")
            .first()
        )
        if destination_bin is None:
            destination_bin = StorageBin.objects.create(store_location=destination_store, bin_code="")

        for item in note.items.select_related("material").all():
            if item.quantity <= 0:
                continue
            InventoryMovement.objects.create(
                movement_type="RECEIPT",
                material=item.material,
                quantity=item.quantity,
                to_store=destination_store,
                to_bin=destination_bin,
                reference_type="DELIVERY_NOTE",
                reference_number=note.note_number,
                notes=f"Site receipt for delivery note {note.note_number}",
                created_by=actor,
            )

        if note.source_requisition_id:
            req = note.source_requisition
            req.status = "FULFILLED"
            req.fulfilled = True
            req.reserved_quantity = Decimal("0.00")
            req.save(update_fields=["status", "fulfilled", "reserved_quantity"])

    context = _base_context(request, "delivery")
    if request.method == "POST":
        _enforce_manage_access(request.user, "delivery")
        note_id = request.POST.get("note_id")
        action = request.POST.get("action")
        note = get_object_or_404(DeliveryNote.objects.select_related("source_requisition"), pk=note_id)

        try:
            with transaction.atomic():
                if action == "approve" and note.status == "DRAFT":
                    note.status = "APPROVED"
                    note.approved_by = request.user
                    note.approved_at = timezone.now()
                    note.save(update_fields=["status", "approved_by", "approved_at"])
                    _log_action(request, "UPDATE", "DeliveryNote", note.id, f"Approved delivery note {note.note_number}")
                elif action == "dispatch" and note.status == "APPROVED":
                    if note.stock_posted:
                        raise ValidationError("Stock has already been posted for this delivery note.")
                    _deduct_hq_for_note(note, request.user)
                    note.status = "DISPATCHED"
                    note.dispatched_by = request.user
                    note.dispatched_at = timezone.now()
                    note.stock_posted = True
                    note.save(update_fields=["status", "dispatched_by", "dispatched_at", "stock_posted"])
                    _log_action(request, "UPDATE", "DeliveryNote", note.id, f"Dispatched delivery note {note.note_number}")
                elif action == "receive" and note.status == "DISPATCHED":
                    _receive_into_site_store(note, request.user)
                    note.status = "RECEIVED"
                    note.received_by_user = request.user
                    note.received_at = timezone.now()
                    note.save(update_fields=["status", "received_by_user", "received_at"])
                    _log_action(request, "UPDATE", "DeliveryNote", note.id, f"Marked delivery note {note.note_number} as received")
                else:
                    messages.warning(request, "Delivery note action is not valid for current status.")
                    return redirect("delivery_notes")

                messages.success(request, f"Delivery note {note.note_number}: {action} completed.")
        except ValidationError as exc:
            messages.error(request, str(exc))

        return redirect("delivery_notes")

    context["rows"] = DeliveryNote.objects.select_related("source_requisition").prefetch_related("items__material").order_by("-created_at")
    return render(request, "SupplChain_MNG/delivery_notes.html", context)


@login_required
def delivery_note_create_view(request):
    _enforce_manage_access(request.user, "delivery")
    note = DeliveryNote(created_by=request.user)
    form = DeliveryNoteForm(request.POST or None, request.FILES or None, instance=note)
    formset = DeliveryNoteItemFormSet(request.POST or None, instance=note, prefix="items")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        note = form.save(commit=False)
        note.created_by = request.user
        note.save()
        formset.instance = note
        formset.save()
        _log_action(request, "CREATE", "DeliveryNote", note.id, f"Created delivery note {note.note_number}")
        return redirect("delivery_notes")

    context = _base_context(request, "delivery")
    context.update({"form": form, "formset": formset, "title": "Create Delivery Note", "is_edit": False})
    return render(request, "SupplChain_MNG/delivery_note_form.html", context)


@login_required
def delivery_note_update_view(request, pk):
    _enforce_manage_access(request.user, "delivery")
    note = get_object_or_404(DeliveryNote, pk=pk)
    if note.status in {"DISPATCHED", "RECEIVED"}:
        messages.error(request, "Dispatched or received delivery notes cannot be edited.")
        return redirect("delivery_notes")
    form = DeliveryNoteForm(request.POST or None, request.FILES or None, instance=note)
    formset = DeliveryNoteItemFormSet(request.POST or None, instance=note, prefix="items")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        note = form.save()
        formset.save()
        _log_action(request, "UPDATE", "DeliveryNote", note.id, f"Updated delivery note {note.note_number}")
        return redirect("delivery_notes")

    context = _base_context(request, "delivery")
    context.update({"form": form, "formset": formset, "title": "Edit Delivery Note", "is_edit": True, "note": note})
    return render(request, "SupplChain_MNG/delivery_note_form.html", context)


@login_required
def delivery_note_delete_view(request, pk):
    _enforce_manage_access(request.user, "delivery")
    note = get_object_or_404(DeliveryNote, pk=pk)
    if note.status in {"DISPATCHED", "RECEIVED"}:
        messages.error(request, "Dispatched or received delivery notes cannot be deleted.")
        return redirect("delivery_notes")
    if request.method == "POST":
        _log_action(request, "DELETE", "DeliveryNote", note.id, f"Deleted delivery note {note.note_number}")
        note.delete()
        return redirect("delivery_notes")

    context = _base_context(request, "delivery")
    context.update({"title": "Delete Delivery Note", "object": note, "cancel_route": "delivery_notes"})
    return render(request, "SupplChain_MNG/crud_confirm_delete.html", context)


@login_required
def delivery_note_pdf_view(request, pk):
    note = get_object_or_404(DeliveryNote.objects.prefetch_related("items__material"), pk=pk)
    profile = CompanyProfile.objects.first()

    reportlab_modules = _load_reportlab_modules()
    if reportlab_modules is None:
        return HttpResponse("PDF export requires reportlab package.", status=501)

    A4, mm, ImageReader, pdf_canvas = reportlab_modules

    buffer = BytesIO()
    pdf = pdf_canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    header_name = profile.company_name if profile else (note.company_name or "")
    header_address = profile.company_address if profile else (note.company_address or "")
    header_logo = profile.logo if profile and profile.logo else note.company_logo

    y = height - 20 * mm
    if header_logo:
        try:
            logo = ImageReader(header_logo.path)
            pdf.drawImage(logo, 15 * mm, y - 15 * mm, width=28 * mm, height=15 * mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50 * mm, y, "DELIVERY NOTE")
    pdf.setFont("Helvetica", 10)
    y -= 8 * mm
    pdf.drawString(50 * mm, y, header_name)
    y -= 5 * mm
    for line in header_address.splitlines()[:3]:
        pdf.drawString(50 * mm, y, line)
        y -= 4 * mm

    y -= 4 * mm
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(15 * mm, y, f"Delivery Note No: {note.note_number}")
    pdf.drawString(120 * mm, y, f"Date: {note.date_issued}")
    y -= 7 * mm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(15 * mm, y, f"From Address: {note.from_location}")
    y -= 6 * mm
    pdf.drawString(15 * mm, y, f"To Address: {note.to_location}")
    y -= 10 * mm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(15 * mm, y, "#")
    pdf.drawString(25 * mm, y, "Material")
    pdf.drawString(140 * mm, y, "Quantity")
    y -= 4 * mm
    pdf.line(15 * mm, y, 190 * mm, y)
    y -= 5 * mm

    pdf.setFont("Helvetica", 10)
    for idx, item in enumerate(note.items.all(), start=1):
        pdf.drawString(15 * mm, y, str(idx))
        pdf.drawString(25 * mm, y, item.material.name)
        pdf.drawRightString(185 * mm, y, f"{item.quantity} {item.material.unit}")
        y -= 6 * mm
        if y < 35 * mm:
            pdf.showPage()
            y = height - 25 * mm

    y -= 10 * mm
    pdf.line(15 * mm, y, 70 * mm, y)
    pdf.line(80 * mm, y, 135 * mm, y)
    pdf.line(145 * mm, y, 200 * mm, y)
    y -= 5 * mm
    pdf.drawString(15 * mm, y, f"Prepared By: {note.prepared_by}")
    pdf.drawString(80 * mm, y, f"Delivered By: {note.delivered_by}")
    pdf.drawString(145 * mm, y, f"Received By: {note.received_by}")

    if note.notes:
        y -= 10 * mm
        pdf.drawString(15 * mm, y, f"Notes: {note.notes[:140]}")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{note.note_number}.pdf"'
    return response


@login_required
def company_profile_view(request):
    _enforce_manage_access(request.user, "delivery")
    profile = CompanyProfile.objects.first() or CompanyProfile()
    form = CompanyProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        saved_profile = form.save()
        _log_action(request, "UPDATE", "CompanyProfile", saved_profile.id, "Updated delivery note company profile")
        return redirect("delivery_notes")

    context = _base_context(request, "delivery")
    context.update({"form": form, "title": "Company Profile"})
    return render(request, "SupplChain_MNG/company_profile_form.html", context)


@login_required
def role_management_view(request):
    if not _is_ops_manager(request.user):
        raise PermissionDenied("Only Operations Manager can manage roles.")

    role_names = ["Operations Manager", "Storekeeper", "Fleet Officer"]

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        role_name = request.POST.get("role_name")
        action = request.POST.get("action")

        target_user = get_object_or_404(User, pk=user_id)
        if role_name in role_names:
            role_group = Group.objects.get(name=role_name)
            if action == "add":
                target_user.groups.add(role_group)
                _log_action(request, "ASSIGN_ROLE", "User", target_user.id, f"Added {role_name} to {target_user.username}")
            elif action == "remove":
                target_user.groups.remove(role_group)
                _log_action(request, "ASSIGN_ROLE", "User", target_user.id, f"Removed {role_name} from {target_user.username}")
        return redirect("role_management")

    users = User.objects.all().order_by("username")
    groups = Group.objects.filter(name__in=role_names).order_by("name")

    context = _base_context(request, "roles")
    context.update({"users": users, "groups": groups, "role_names": role_names})
    return render(request, "SupplChain_MNG/role_management.html", context)


@login_required
def audit_log_view(request):
    if not _is_ops_manager(request.user):
        raise PermissionDenied("Only Operations Manager can view audit logs.")

    context = _base_context(request, "audit")
    context["rows"] = AuditLog.objects.select_related("user")[:200]
    return render(request, "SupplChain_MNG/audit_log.html", context)


@login_required
def fleet_management_view(request):
    context = _base_context(request, "fleet")
    today = timezone.localdate()
    soon = today + timedelta(days=30)

    equipment_rows = _filter_by_store_scope(
        MobileEquipment.objects.select_related("assigned_driver", "project", "store_location").order_by("name"),
        request.user,
        "store_location_id",
    )
    if context["filters"]["name"]:
        equipment_rows = equipment_rows.filter(name__icontains=context["filters"]["name"])
    if context["filters"]["code_number"]:
        equipment_rows = equipment_rows.filter(registration_number__icontains=context["filters"]["code_number"])

    equipment_rows = list(equipment_rows)
    for item in equipment_rows:
        item.service_due_meta = _due_meta(item.service_due_date)
        item.road_tax_due_meta = _due_meta(item.road_tax_due_date)
        item.fitness_due_meta = _due_meta(item.fitness_due_date)
        item.insurance_due_meta = _due_meta(item.insurance_due_date)

    driver_rows = list(Driver.objects.order_by("full_name"))
    for item in driver_rows:
        item.license_due_meta = _due_meta(item.license_expiry)

    fuel_rows = _filter_by_store_scope(
        FleetFuelLog.objects.select_related("equipment", "equipment__store_location", "consumable").order_by("-date_logged"),
        request.user,
        "equipment__store_location_id",
    )
    maintenance_rows = _filter_by_store_scope(
        FleetMaintenance.objects.select_related("equipment", "equipment__store_location").order_by("-start_date"),
        request.user,
        "equipment__store_location_id",
    )

    movement_rows = InventoryMovement.objects.select_related(
        "material", "from_store", "from_bin", "to_store", "to_bin", "created_by"
    ).order_by("-created_at")

    scoped_store_ids = _scoped_store_ids(request.user)
    if scoped_store_ids is not None:
        movement_rows = movement_rows.filter(Q(to_store_id__in=scoped_store_ids) | Q(from_store_id__in=scoped_store_ids))

    if context["filters"]["name"]:
        movement_rows = movement_rows.filter(material__name__icontains=context["filters"]["name"])
    if context["filters"]["code_number"]:
        movement_rows = movement_rows.filter(material__code_number__icontains=context["filters"]["code_number"])

    fuel_usage_total = fuel_rows.aggregate(total=Sum("quantity"))["total"] or 0
    inactive_fleets_count = len([row for row in equipment_rows if not row.is_active])
    maintenance_due_count = len([row for row in equipment_rows if row.service_due_date and row.service_due_date <= soon])

    def _fleet_due_rows(date_attr):
        rows = []
        for eq in equipment_rows:
            due_date = getattr(eq, date_attr)
            if not due_date:
                continue
            rows.append(
                {
                    "name": eq.name,
                    "location": eq.store_location.name if eq.store_location else "-",
                    "due_date": due_date.strftime("%Y-%m-%d"),
                    "status": _due_meta(due_date)["label"],
                }
            )
        return rows

    fleet_dialog_data = {
        "total_vehicles": [
            {
                "name": eq.name,
                "location": eq.store_location.name if eq.store_location else "-",
                "due_date": "-",
                "status": "Active" if eq.is_active else "Inactive",
            }
            for eq in equipment_rows
        ],
        "active_vehicles": [
            {
                "name": eq.name,
                "location": eq.store_location.name if eq.store_location else "-",
                "due_date": "-",
                "status": "Active",
            }
            for eq in equipment_rows
            if eq.is_active
        ],
        "inactive_vehicles": [
            {
                "name": eq.name,
                "location": eq.store_location.name if eq.store_location else "-",
                "due_date": "-",
                "status": "Inactive",
            }
            for eq in equipment_rows
            if not eq.is_active
        ],
        "maintenance_due": _fleet_due_rows("service_due_date"),
        "road_tax_due": _fleet_due_rows("road_tax_due_date"),
        "fitness_due": _fleet_due_rows("fitness_due_date"),
        "insurance_due": _fleet_due_rows("insurance_due_date"),
        "fuel_usage": [
            {
                "name": row["equipment__name"] or "-",
                "location": row["equipment__store_location__name"] or "-",
                "due_date": row["last_logged"].strftime("%Y-%m-%d") if row["last_logged"] else "-",
                "status": "Tracked",
            }
            for row in fuel_rows.values("equipment__name", "equipment__store_location__name")
            .annotate(total=Sum("quantity"), last_logged=Max("date_logged"))
            .order_by("-total")
        ],
    }

    context.update(
        {
            "equipment_rows": equipment_rows,
            "driver_rows": driver_rows,
            "fuel_rows": fuel_rows[:20],
            "maintenance_rows": maintenance_rows[:20],
            "movement_rows": movement_rows[:120],
            "can_manage_inventory_movements": _can_manage_section(request.user, "inventory"),
            "active_fleets_count": len([row for row in equipment_rows if row.status == "ACTIVE"]),
            "in_maintenance_count": len([row for row in equipment_rows if row.status == "REPAIRING"]),
            "broken_count": len([row for row in equipment_rows if row.status == "BREAKDOWN"]),
            "due_service_count": len([row for row in equipment_rows if row.service_due_date and row.service_due_date <= soon]),
            "due_road_tax_count": len([row for row in equipment_rows if row.road_tax_due_date and row.road_tax_due_date <= soon]),
            "due_fitness_count": len([row for row in equipment_rows if row.fitness_due_date and row.fitness_due_date <= soon]),
            "due_insurance_count": len([row for row in equipment_rows if row.insurance_due_date and row.insurance_due_date <= soon]),
            "due_license_count": len([row for row in driver_rows if row.license_expiry and row.license_expiry <= soon]),
            "total_vehicles_count": len(equipment_rows),
            "inactive_fleets_count": inactive_fleets_count,
            "maintenance_due_count": maintenance_due_count,
            "fuel_usage_total": fuel_usage_total,
            "fleet_dialog_data_json": json.dumps(fleet_dialog_data),
        }
    )
    return render(request, "SupplChain_MNG/fleet_management.html", context)


@login_required
def analytics_view(request):
    context = _base_context(request, "analytics")
    materials = context["materials"]
    requisitions = context["requisitions"]
    transactions = context["transactions"]

    top_materials = list(materials.values("name").annotate(total=Sum("quantity")).order_by("-total")[:8])
    top_requested = list(
        requisitions.values("material__name")
        .annotate(total=Sum("quantity_requested"))
        .order_by("-total")[:8]
    )
    transaction_split = list(
        transactions.values("transaction_type").annotate(total=Sum("quantity")).order_by("transaction_type")
    )
    fleet_status = list(
        MobileEquipment.objects.values("status").annotate(total=Count("id")).order_by("status")
    )
    equipment_status = list(
        Equipment.objects.values("status").annotate(total=Count("id")).order_by("status")
    )
    due_window = timezone.localdate() + timedelta(days=30)
    due_summary = [
        {"label": "Service", "count": MobileEquipment.objects.filter(service_due_date__isnull=False, service_due_date__lte=due_window).count()},
        {"label": "Road Tax", "count": MobileEquipment.objects.filter(road_tax_due_date__isnull=False, road_tax_due_date__lte=due_window).count()},
        {"label": "Fitness", "count": MobileEquipment.objects.filter(fitness_due_date__isnull=False, fitness_due_date__lte=due_window).count()},
        {"label": "Insurance", "count": MobileEquipment.objects.filter(insurance_due_date__isnull=False, insurance_due_date__lte=due_window).count()},
    ]
    fuel_by_type = list(
        FleetFuelLog.objects.values("fluid_type").annotate(total=Sum("quantity")).order_by("fluid_type")
    )
    fuel_trend = list(
        FleetFuelLog.objects.annotate(month=TruncMonth("date_logged"))
        .values("month")
        .annotate(total=Sum("quantity"))
        .order_by("month")
    )
    maintenance_cost_trend = list(
        FleetMaintenance.objects.annotate(month=TruncMonth("start_date"))
        .values("month")
        .annotate(total=Sum("cost"))
        .order_by("month")
    )

    context.update(
        {
            "total_in": transactions.filter(transaction_type="IN").aggregate(total=Sum("quantity"))["total"] or 0,
            "total_out": transactions.filter(transaction_type="OUT").aggregate(total=Sum("quantity"))["total"] or 0,
            "return_volume": context["returns"].aggregate(total=Sum("quantity_returned"))["total"] or 0,
            "fulfillment_rate": (
                round((requisitions.filter(fulfilled=True).count() / requisitions.count()) * 100, 2)
                if requisitions.count()
                else 0
            ),
            "top_materials_json": json.dumps(top_materials),
            "top_requested_json": json.dumps(top_requested),
            "transaction_split_json": json.dumps(transaction_split),
            "fleet_status_json": json.dumps(fleet_status),
            "equipment_status_json": json.dumps(equipment_status),
            "due_summary_json": json.dumps(due_summary),
            "fuel_by_type_json": json.dumps(fuel_by_type),
            "fuel_trend_json": json.dumps([
                {"month": item["month"].strftime("%Y-%m") if item["month"] else "Unknown", "total": float(item["total"] or 0)}
                for item in fuel_trend
            ]),
            "maintenance_cost_trend_json": json.dumps([
                {"month": item["month"].strftime("%Y-%m") if item["month"] else "Unknown", "total": float(item["total"] or 0)}
                for item in maintenance_cost_trend
            ]),
        }
    )
    return render(request, "SupplChain_MNG/analytics.html", context)


@login_required
def record_create(request, entity):
    cfg = _crud_cfg(entity)
    _enforce_manage_access(request.user, cfg["active_tab"])

    if entity == "requisitions":
        req = Requisition(requested_by=request.user, status="DRAFT")
        form = WorkspaceRequisitionForm(request.POST or None, instance=req)
        formset = RequisitionItemFormSet(request.POST or None, instance=req, prefix="items")

        if request.method == "POST" and form.is_valid() and formset.is_valid():
            req = form.save(commit=False)
            req.status = "DRAFT"
            if not req.requested_by_id:
                req.requested_by = request.user
            req.save()
            formset.instance = req
            formset.save()
            _log_action(
                request,
                "CREATE",
                cfg["label"],
                req.id,
                f"Created multi-item requisition {req.req_number}",
            )
            messages.success(request, f"Requisition {req.req_number} created.")
            return redirect(cfg["route"])

        context = _base_context(request, cfg["active_tab"])
        context.update(
            {
                "form": form,
                "formset": formset,
                "title": "Create Requisition",
                "cancel_url": reverse(cfg["route"]),
            }
        )
        return render(request, "SupplChain_MNG/project_requisition_form.html", context)

    if entity == "inventory-movements":
        header_form = InventoryMovementHeaderForm(request.POST or None)
        formset = MovementItemFormSet(request.POST or None, prefix="items")

        if request.method == "POST" and header_form.is_valid() and formset.is_valid():
            h = header_form.cleaned_data
            created = []
            try:
                with transaction.atomic():
                    for item_form in formset:
                        cd = item_form.cleaned_data
                        if not cd or cd.get("DELETE"):
                            continue
                        mvt = InventoryMovement(
                            movement_type=h["movement_type"],
                            material=cd["material"],
                            quantity=cd["quantity"],
                            from_store=h.get("from_store"),
                            from_bin=h.get("from_bin"),
                            to_store=h.get("to_store"),
                            to_bin=h.get("to_bin"),
                            driver=h.get("driver"),
                            mobile_equipment=h.get("mobile_equipment"),
                            delivery_note=h.get("delivery_note"),
                            reference_type=h.get("reference_type") or "",
                            reference_number=h.get("reference_number") or "",
                            notes=h.get("notes") or "",
                            created_by=request.user,
                        )
                        mvt.save()
                        created.append(mvt)
            except ValidationError as exc:
                header_form.add_error(None, exc)
            else:
                count = len(created)
                _log_action(request, "CREATE", cfg["label"], "", f"Created {count} inventory movement(s)")
                messages.success(request, f"{count} inventory movement(s) created.")
                return redirect(cfg["route"])

        context = _base_context(request, cfg["active_tab"])
        context.update(
            {
                "form": header_form,
                "formset": formset,
                "title": "Create Inventory Movement",
                "cancel_url": reverse(cfg["route"]),
            }
        )
        return render(request, "SupplChain_MNG/inventory_movement_form.html", context)

    form = cfg["form"](request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            obj = form.save(commit=False)
            if entity == "inventory-movements" and not getattr(obj, "created_by_id", None):
                obj.created_by = request.user
            obj.save()
            form.save_m2m()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            _log_action(request, "CREATE", cfg["label"], getattr(obj, "id", ""), f"Created {cfg['label']}")
            return redirect(cfg["route"])

    context = _base_context(request, cfg["active_tab"])
    context.update(
        {
            "form": form,
            "title": f"Create {cfg['label']}",
            "submit_label": "Create",
            "cancel_route": cfg["route"],
        }
    )
    template = "SupplChain_MNG/inventory_movement_form.html" if entity == "inventory-movements" else "SupplChain_MNG/crud_form.html"
    return render(request, template, context)


@login_required
def record_update(request, entity, pk):
    cfg = _crud_cfg(entity)
    _enforce_manage_access(request.user, cfg["active_tab"])
    obj = get_object_or_404(cfg["model"], pk=pk)
    form = cfg["form"](request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        try:
            obj = form.save(commit=False)
            if entity == "inventory-movements" and not getattr(obj, "created_by_id", None):
                obj.created_by = request.user
            obj.save()
            form.save_m2m()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            _log_action(request, "UPDATE", cfg["label"], getattr(obj, "id", ""), f"Updated {cfg['label']}")
            return redirect(cfg["route"])

    context = _base_context(request, cfg["active_tab"])
    context.update(
        {
            "form": form,
            "title": f"Edit {cfg['label']}",
            "submit_label": "Save",
            "cancel_route": cfg["route"],
        }
    )
    template = "SupplChain_MNG/inventory_movement_form.html" if entity == "inventory-movements" else "SupplChain_MNG/crud_form.html"
    return render(request, template, context)


@login_required
def record_delete(request, entity, pk):
    cfg = _crud_cfg(entity)
    _enforce_manage_access(request.user, cfg["active_tab"])
    obj = get_object_or_404(cfg["model"], pk=pk)
    if request.method == "POST":
        _log_action(request, "DELETE", cfg["label"], getattr(obj, "id", ""), f"Deleted {cfg['label']}")
        obj.delete()
        return redirect(cfg["route"])

    context = _base_context(request, cfg["active_tab"])
    context.update(
        {
            "title": f"Delete {cfg['label']}",
            "object": obj,
            "cancel_route": cfg["route"],
        }
    )
    return render(request, "SupplChain_MNG/crud_confirm_delete.html", context)


@login_required
def export_records(request, entity, fmt):
    _crud_cfg(entity)
    fields = EXPORT_FIELDS.get(entity)
    if not fields:
        raise Http404("No export mapping found")

    qs = _get_filtered_export_queryset(entity, request)
    headers = [label for _, label in fields]
    values = [path for path, _ in fields]
    rows = list(qs.values_list(*values))

    if fmt == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{entity}.csv"'
        writer = csv.writer(response)
        writer.writerow(headers)
        writer.writerows(rows)
        return response

    if fmt == "excel":
        if Workbook is None:
            return HttpResponse("Excel export requires openpyxl package.", status=501)

        wb = Workbook()
        ws = wb.active
        ws.title = entity[:31]
        ws.append(headers)
        for row in rows:
            ws.append(list(row))

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{entity}.xlsx"'
        wb.save(response)
        return response

    raise Http404("Unsupported export format")


# ─── Settings hub ────────────────────────────────────────────────────────────

@login_required
def settings_view(request):
    context = _base_context(request, "settings")
    return render(request, "SupplChain_MNG/settings.html", context)


# ─── Per-project Manage hub ───────────────────────────────────────────────────

@login_required
def project_manage_view(request, pk):
    project = get_object_or_404(Project, pk=pk)
    context = _base_context(request, "project_manage")

    project_store_ids = list(
        StoreLocation.objects.filter(project=project).values_list("id", flat=True)
    )

    recent_receipts = list(
        GoodsReceipt.objects.filter(destination_store_id__in=project_store_ids)
        .select_related("destination_store")
        .prefetch_related("items")
        .order_by("-created_at")[:8]
    )
    for r in recent_receipts:
        lines = list(r.items.all())
        r.item_count = len(lines)
        r.total_qty = sum([l.quantity for l in lines], Decimal("0.00"))

    recent_issues = list(
        GoodsIssue.objects.filter(source_store_id__in=project_store_ids)
        .select_related("source_store")
        .prefetch_related("items")
        .order_by("-created_at")[:8]
    )
    for r in recent_issues:
        lines = list(r.items.all())
        r.item_count = len(lines)
        r.total_qty = sum([l.quantity for l in lines], Decimal("0.00"))

    recent_returns = list(
        GoodsReturn.objects.filter(destination_store_id__in=project_store_ids)
        .select_related("destination_store", "from_store")
        .prefetch_related("items")
        .order_by("-created_at")[:8]
    )
    for r in recent_returns:
        lines = list(r.items.all())
        r.item_count = len(lines)
        r.total_qty = sum([l.quantity for l in lines], Decimal("0.00"))

    recent_ppe = list(
        PPEIssue.objects.filter(store_location_id__in=project_store_ids)
        .select_related("store_location")
        .prefetch_related("items")
        .order_by("-created_at")[:8]
    )
    for r in recent_ppe:
        lines = list(r.items.all())
        r.item_count = len(lines)
        r.total_qty = sum([l.quantity for l in lines], Decimal("0.00"))

    recent_reqs = list(
        Requisition.objects.filter(project=project)
        .select_related("requested_by")
        .prefetch_related("items")
        .order_by("-date_requested")[:8]
    )

    context.update(
        {
            "project": project,
            "project_stores": StoreLocation.objects.filter(project=project),
            "recent_receipts": recent_receipts,
            "receipt_count": GoodsReceipt.objects.filter(destination_store_id__in=project_store_ids).count(),
            "recent_issues": recent_issues,
            "issue_count": GoodsIssue.objects.filter(source_store_id__in=project_store_ids).count(),
            "recent_returns": recent_returns,
            "return_count": GoodsReturn.objects.filter(destination_store_id__in=project_store_ids).count(),
            "recent_ppe": recent_ppe,
            "ppe_count": PPEIssue.objects.filter(store_location_id__in=project_store_ids).count(),
            "recent_reqs": recent_reqs,
            "req_count": Requisition.objects.filter(project=project).count(),
        }
    )
    return render(request, "SupplChain_MNG/project_manage.html", context)


@login_required
def project_requisition_create_view(request, pk):
    project = get_object_or_404(Project, pk=pk)
    _enforce_manage_access(request.user, "requisitions")

    req = Requisition(project=project, requested_by=request.user, status="DRAFT")
    form = ProjectRequisitionForm(request.POST or None, instance=req)
    formset = RequisitionItemFormSet(request.POST or None, instance=req, prefix="items")

    if request.method == "POST" and form.is_valid() and formset.is_valid():
        req = form.save(commit=False)
        req.project = project
        req.requested_by = request.user
        req.status = "DRAFT"
        req.save()
        formset.instance = req
        formset.save()
        _log_action(
            request,
            "CREATE",
            "Requisition",
            req.id,
            f"Created multi-item requisition {req.req_number} for project {project.name}",
        )
        messages.success(request, f"Requisition {req.req_number} created.")
        return redirect("project_manage", pk=project.pk)

    context = _base_context(request, "requisitions")
    context.update(
        {
            "project": project,
            "form": form,
            "formset": formset,
            "title": f"New Requisition — {project.name}",
        }
    )
    return render(request, "SupplChain_MNG/project_requisition_form.html", context)


# ─── Material stock API (JSON) ────────────────────────────────────────────────

@login_required
def material_stock_api(request, pk):
    material = get_object_or_404(Material, pk=pk)
    return JsonResponse(
        {
            "quantity": str(material.quantity),
            "min_required": str(material.min_required),
        }
    )


@login_required
def store_bins_api(request, pk):
    """Return active bins for a store as JSON – used by AJAX bin dropdowns."""
    store = get_object_or_404(StoreLocation, pk=pk)
    bins = StorageBin.objects.filter(store_location=store, is_active=True).order_by("bin_code")
    return JsonResponse({"bins": [{"id": b.pk, "label": str(b)} for b in bins]})


@login_required
def delivery_note_materials_api(request, pk):
    """Return materials from a delivery note as JSON."""
    delivery_note = get_object_or_404(DeliveryNote, pk=pk)
    items = delivery_note.items.all()
    return JsonResponse({
        "materials": [
            {"id": item.material_id, "name": item.material.name, "quantity": str(item.quantity)}
            for item in items
        ]
    })
