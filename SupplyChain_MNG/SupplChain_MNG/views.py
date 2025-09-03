from django.shortcuts import render
from .models import Material, Category, Requisition, StockTransaction, DEPARTMENTS
from django.db.models import Count, Sum, F
import json

def home(request):
    # Summary metrics
    total_materials = Material.objects.count()
    low_stock = Material.objects.filter(quantity__lte=F('min_required'))
    low_stock_count = low_stock.count()
    total_categories = Category.objects.count()
    total_requisitions = Requisition.objects.count()
    pending_requisitions = Requisition.objects.filter(fulfilled=False).count()  # <-- FIXED HERE
    total_transactions = StockTransaction.objects.count()
    total_quantity = Material.objects.aggregate(total=Sum('quantity'))['total'] or 0

    # For filters
    category_choices = Category.objects.all()
    department_choices = DEPARTMENTS  # This gives you all (value, display name) pairs

    # Chart data
    category_counts = list(Category.objects.annotate(material_count=Count('material')).values('name', 'material_count'))
    transaction_counts = list(StockTransaction.objects.values('transaction_type').annotate(count=Count('id')))
    requisition_counts = list(Requisition.objects.values('department').annotate(count=Count('id')))
    material_counts = list(Material.objects.values('name', 'quantity'))

    # Recent transactions table
    recent_transactions = StockTransaction.objects.select_related('material', 'performed_by').order_by('-date')[:10]

    return render(request, 'SupplChain_MNG/home.html', {
        'total_materials': total_materials,
        'low_stock_count': low_stock_count,
        'total_categories': total_categories,
        'total_requisitions': total_requisitions,
        'pending_requisitions': pending_requisitions,
        'total_transactions': total_transactions,
        'total_quantity': total_quantity,
        'category_choices': category_choices,
        'department_choices': department_choices,
        'category_counts_json': json.dumps(category_counts),
        'transaction_counts_json': json.dumps(transaction_counts),
        'requisition_counts_json': json.dumps(requisition_counts),
        'material_counts_json': json.dumps(material_counts),
        'recent_transactions': [
            {
                'date': t.date.strftime('%Y-%m-%d'),
                'material': t.material.name,
                'transaction_type': t.transaction_type,
                'quantity': t.quantity,
                'user': t.performed_by.username if t.performed_by else 'N/A'
            } for t in recent_transactions
        ],
        'low_stock': low_stock,
    })
