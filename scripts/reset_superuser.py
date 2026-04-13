import os, sys
sys.path.insert(0, r"C:\Users\PC\OneDrive\Desktop\SupplyChain_MNG")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "SupplyChain_MNG.settings")
import django

django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

PASSWORD = "Admin@12345!"  # Temporary password; change after login
USERNAME = "admin"
EMAIL = "admin@example.com"

qs = User.objects.filter(is_superuser=True)
if qs.exists():
    u = qs.first()
    u.set_password(PASSWORD)
    u.is_staff = True
    u.save()
    print(f"EXISTING superuser reset: {u.username}")
else:
    if User.objects.filter(username=USERNAME).exists():
        u = User.objects.get(username=USERNAME)
        u.is_superuser = True
        u.is_staff = True
        u.set_password(PASSWORD)
        u.email = u.email or EMAIL
        u.save()
        print(f"UPGRADED existing user to superuser: {u.username}")
    else:
        u = User.objects.create_user(username=USERNAME, email=EMAIL, password=PASSWORD)
        u.is_staff = True
        u.is_superuser = True
        u.save()
        print(f"CREATED new superuser: {u.username}")
