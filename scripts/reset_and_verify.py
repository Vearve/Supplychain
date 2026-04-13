import os, sys
sys.path.insert(0, r"C:\Users\PC\OneDrive\Desktop\SupplyChain_MNG")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "SupplyChain_MNG.settings")
import django

django.setup()

from django.contrib.auth import get_user_model, authenticate

User = get_user_model()

users = list(User.objects.all().values("id","username","is_active","is_staff","is_superuser"))
print({"users": users})

username = None
su = User.objects.filter(is_superuser=True).order_by("id").first()
if su:
    username = su.username
else:
    if User.objects.filter(username="admin").exists():
        username = "admin"
    elif users:
        username = users[0]["username"]

if not username:
    print({"action": "create", "username": "admin"})
    u = User.objects.create_user(username="admin", email="admin@example.com", password="TempAdmin!2026")
    u.is_staff = True
    u.is_superuser = True
    u.is_active = True
    u.save()
    username = "admin"
    pwd = "TempAdmin!2026"
else:
    u = User.objects.get(username=username)
    pwd = "TempAdmin!2026"
    u.set_password(pwd)
    u.is_active = True
    if not u.is_staff:
        u.is_staff = True
    if not u.is_superuser:
        u.is_superuser = True
    u.save()
    print({"action": "reset", "username": username})

user = authenticate(username=username, password=pwd)
print({"auth": bool(user), "username": username, "password": pwd})
