from django.contrib import admin
from .models import (
    AuditLog,
    Category,
    CompanyProfile,
    DeliveryNote,
    DeliveryNoteItem,
    Driver,
    Equipment,
    FleetFuelLog,
    FleetMaintenance,
    GoodsIssue,
    GoodsIssueItem,
    GoodsReceipt,
    GoodsReceiptItem,
    GoodsReturn,
    GoodsReturnItem,
    Material,
    MaterialReturn,
    MobileEquipment,
    PPEIssue,
    PPEIssueItem,
    Project,
    Requisition,
    RequisitionReadReceipt,
    RequisitionReservation,
    StoreLocation,
    StorageBin,
    InventoryBalance,
    InventoryMovement,
    StockTransaction,
    SubCategory,
    UserStoreScope,
)

# Custom Admin Branding
admin.site.site_header = "Leos Investments Ltd Supply Chain Management"
admin.site.site_title = "Leos Admin"
admin.site.index_title = "Store Management Dashboard"

# Inline for SubCategory in Category
class SubCategoryInline(admin.TabularInline):
    model = SubCategory
    extra = 0

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ['name']
    inlines = [SubCategoryInline]

# Inline for Material in SubCategory
class MaterialInline(admin.TabularInline):
    model = Material
    extra = 0

@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'category']
    search_fields = ['name', 'category__name']
    list_filter = ['category']
    inlines = [MaterialInline]


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'serial_number', 'subcategory', 'project', 'store_location', 'status', 'location', 'service_due_date', 'is_active']
    search_fields = ['name', 'serial_number', 'subcategory__name', 'project__name']
    list_filter = ['status', 'is_active', 'subcategory', 'project', 'store_location']

@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ['name', 'code_number', 'part_number', 'is_consumable', 'measurement_unit', 'quantity', 'min_required', 'category', 'subcategory', 'location', 'photo', 'document']
    search_fields = ['name', 'part_number', 'code_number']
    list_filter = ['is_consumable', 'measurement_unit', 'category', 'subcategory', 'location']

@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ['code_number', 'material', 'transaction_type', 'quantity', 'performed_by', 'date']
    search_fields = ['code_number', 'material__name', 'performed_by__username']
    list_filter = ['transaction_type', 'date']

@admin.register(Requisition)
class RequisitionAdmin(admin.ModelAdmin):
    list_display = ['code_number', 'material', 'quantity_requested', 'department', 'project', 'requested_by', 'status', 'reserved_quantity', 'fulfilled', 'date_requested']
    search_fields = ['code_number', 'material__name', 'requested_by__username']
    list_filter = ['department', 'status', 'fulfilled']


@admin.register(RequisitionReadReceipt)
class RequisitionReadReceiptAdmin(admin.ModelAdmin):
    list_display = ['user', 'requisition', 'read_at']
    search_fields = ['user__username', 'requisition__code_number', 'requisition__material__name']
    list_filter = ['read_at']


@admin.register(RequisitionReservation)
class RequisitionReservationAdmin(admin.ModelAdmin):
    list_display = ['requisition', 'inventory_balance', 'quantity', 'created_at']
    search_fields = ['requisition__code_number', 'requisition__material__name', 'inventory_balance__material__name']
    list_filter = ['created_at']

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    search_fields = ['name']


@admin.register(StoreLocation)
class StoreLocationAdmin(admin.ModelAdmin):
    list_display = ['name', 'location_type', 'project', 'is_active']
    search_fields = ['name', 'project__name']
    list_filter = ['location_type', 'is_active']


@admin.register(StorageBin)
class StorageBinAdmin(admin.ModelAdmin):
    list_display = ['store_location', 'bin_code', 'zone', 'aisle', 'rack', 'shelf', 'is_active']
    search_fields = ['store_location__name', 'bin_code', 'zone', 'aisle', 'rack', 'shelf', 'description']
    list_filter = ['store_location', 'is_active']


@admin.register(InventoryBalance)
class InventoryBalanceAdmin(admin.ModelAdmin):
    list_display = ['material', 'storage_bin', 'on_hand', 'reserved', 'updated_at']
    search_fields = ['material__name', 'material__code_number', 'storage_bin__bin_code', 'storage_bin__store_location__name']
    list_filter = ['storage_bin__store_location']


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'movement_type', 'material', 'quantity', 'from_store', 'from_bin', 'to_store', 'to_bin', 'reference_type', 'reference_number']
    search_fields = ['material__name', 'material__code_number', 'reference_type', 'reference_number', 'from_store__name', 'to_store__name']
    list_filter = ['movement_type', 'created_at', 'from_store', 'to_store']

@admin.register(MaterialReturn)
class MaterialReturnAdmin(admin.ModelAdmin):
    list_display = ['material', 'project', 'quantity_returned', 'returned_by', 'date_returned', 'code_number']
    search_fields = ['material__name', 'project__name', 'code_number', 'returned_by__username']
    list_filter = ['project', 'date_returned']

    def code_number(self, obj):
        return obj.material.code_number if obj.material else ''
    code_number.short_description = 'Code Number'


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'phone_number', 'license_number', 'license_expiry', 'is_active']
    search_fields = ['full_name', 'license_number']
    list_filter = ['is_active']


@admin.register(MobileEquipment)
class MobileEquipmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'registration_number', 'equipment_type', 'status', 'assigned_driver', 'project', 'store_location', 'is_active']
    search_fields = ['name', 'registration_number', 'equipment_type']
    list_filter = ['status', 'is_active', 'project', 'store_location']


@admin.register(FleetFuelLog)
class FleetFuelLogAdmin(admin.ModelAdmin):
    list_display = ['equipment', 'fluid_type', 'quantity', 'unit', 'odometer_at_fill', 'date_logged']
    search_fields = ['equipment__name', 'equipment__registration_number', 'consumable__name']
    list_filter = ['fluid_type', 'unit', 'date_logged']


@admin.register(FleetMaintenance)
class FleetMaintenanceAdmin(admin.ModelAdmin):
    list_display = ['equipment', 'maintenance_type', 'status', 'start_date', 'end_date', 'cost']
    search_fields = ['equipment__name', 'service_provider']
    list_filter = ['maintenance_type', 'status', 'start_date']


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'updated_at']
    search_fields = ['company_name', 'company_address']


class DeliveryNoteItemInline(admin.TabularInline):
    model = DeliveryNoteItem
    extra = 0


class GoodsReceiptItemInline(admin.TabularInline):
    model = GoodsReceiptItem
    extra = 0


class GoodsIssueItemInline(admin.TabularInline):
    model = GoodsIssueItem
    extra = 0


class GoodsReturnItemInline(admin.TabularInline):
    model = GoodsReturnItem
    extra = 0


class PPEIssueItemInline(admin.TabularInline):
    model = PPEIssueItem
    extra = 0


@admin.register(DeliveryNote)
class DeliveryNoteAdmin(admin.ModelAdmin):
    list_display = ['note_number', 'date_issued', 'status', 'source_requisition', 'from_location', 'to_location', 'prepared_by', 'delivered_by', 'received_by', 'stock_posted', 'created_by']
    search_fields = ['note_number', 'from_location', 'to_location', 'prepared_by', 'delivered_by', 'received_by', 'source_requisition__code_number']
    list_filter = ['status', 'stock_posted', 'date_issued']
    inlines = [DeliveryNoteItemInline]


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = [
        'receipt_number', 'date_received', 'destination_store', 'source_type', 'status',
        'stock_posted', 'prepared_by', 'delivered_by', 'received_by', 'created_by'
    ]
    search_fields = ['receipt_number', 'destination_store__name', 'source_reference', 'prepared_by', 'delivered_by', 'received_by']
    list_filter = ['status', 'source_type', 'stock_posted', 'date_received']
    inlines = [GoodsReceiptItemInline]


@admin.register(GoodsIssue)
class GoodsIssueAdmin(admin.ModelAdmin):
    list_display = [
        'issue_number', 'date_issued', 'source_store', 'department', 'issued_to',
        'status', 'stock_posted', 'issued_by', 'received_by', 'created_by'
    ]
    search_fields = ['issue_number', 'source_store__name', 'department', 'issued_to', 'issued_by', 'received_by']
    list_filter = ['status', 'stock_posted', 'date_issued']
    inlines = [GoodsIssueItemInline]


@admin.register(GoodsReturn)
class GoodsReturnAdmin(admin.ModelAdmin):
    list_display = [
        'return_number', 'date_returned', 'from_store', 'destination_store', 'related_goods_issue',
        'status', 'stock_posted', 'returned_by', 'received_by', 'created_by'
    ]
    search_fields = ['return_number', 'from_store__name', 'destination_store__name', 'returned_by', 'received_by']
    list_filter = ['status', 'stock_posted', 'date_returned']
    inlines = [GoodsReturnItemInline]


@admin.register(PPEIssue)
class PPEIssueAdmin(admin.ModelAdmin):
    list_display = [
        'issue_number', 'date_issued', 'store_location', 'employee_name', 'employee_number',
        'issue_type', 'reason', 'status', 'stock_posted', 'issued_by', 'received_by'
    ]
    search_fields = ['issue_number', 'store_location__name', 'employee_name', 'employee_number', 'department']
    list_filter = ['status', 'stock_posted', 'issue_type', 'reason', 'date_issued']
    inlines = [PPEIssueItemInline]


@admin.register(UserStoreScope)
class UserStoreScopeAdmin(admin.ModelAdmin):
    list_display = ['user', 'store_location', 'can_manage']
    search_fields = ['user__username', 'store_location__name']
    list_filter = ['can_manage', 'store_location']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'action', 'entity', 'entity_id', 'user']
    search_fields = ['action', 'entity', 'description', 'user__username']
    list_filter = ['action', 'entity', 'created_at']
