from django.contrib import admin
from .models import Category, SubCategory, Equipment, Material, StockTransaction, Requisition, Project, MaterialReturn

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

@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ['name', 'part_number', 'quantity', 'min_required', 'category', 'subcategory', 'location']
    search_fields = ['name', 'part_number']
    list_filter = ['category', 'subcategory', 'location']  # <-- Add 'subcategory' here

@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ['code_number', 'material', 'transaction_type', 'quantity', 'performed_by', 'date']
    search_fields = ['code_number', 'material__name', 'performed_by__username']
    list_filter = ['transaction_type', 'date']

@admin.register(Requisition)
class RequisitionAdmin(admin.ModelAdmin):
    list_display = ['code_number', 'material', 'quantity_requested', 'department', 'project', 'requested_by', 'fulfilled', 'date_requested']
    search_fields = ['code_number', 'material__name', 'requested_by__username']
    list_filter = ['department', 'fulfilled']

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    search_fields = ['name']

@admin.register(MaterialReturn)
class MaterialReturnAdmin(admin.ModelAdmin):
    list_display = ['material', 'project', 'quantity_returned', 'returned_by', 'date_returned', 'code_number']
    search_fields = ['material__name', 'project__name', 'code_number', 'returned_by__username']
    list_filter = ['project', 'date_returned']

    def code_number(self, obj):
        return obj.material.code_number if obj.material else ''
    code_number.short_description = 'Code Number'
