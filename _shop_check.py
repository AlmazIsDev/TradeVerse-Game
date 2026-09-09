import sys
sys.path.insert(0, 'backend')
try:
    import shop
except Exception as e:
    print('IMPORT ERROR:', type(e).__name__, e)
    sys.exit(1)
print('items total:', len(shop.CATALOG))
print('admin gpu:', sum(1 for c in shop.ADMIN_CATALOG if c['category'] == 'gpu'))
print('admin cpu:', sum(1 for c in shop.ADMIN_CATALOG if c['category'] == 'cpu'))
print('admin case:', sum(1 for c in shop.ADMIN_CATALOG if c['category'] == 'case'))
print('admin supplies:', sum(1 for c in shop.ADMIN_CATALOG if c['category'] == 'supplies'))
print('admin-gpu-1 name:', shop.CATALOG_BY_ID['admin-gpu-1']['name'])
print('admin-gpu-60 name:', shop.CATALOG_BY_ID['admin-gpu-60']['name'])
print('admin-gpu-90 name:', shop.CATALOG_BY_ID['admin-gpu-90']['name'])
print('admin-cpu-1 name:', shop.CATALOG_BY_ID['admin-cpu-1']['name'])
print('admin-cpu-90 name:', shop.CATALOG_BY_ID['admin-cpu-90']['name'])
print('admin-case-1 name:', shop.CATALOG_BY_ID['admin-case-1']['name'])
print('admin-case-90 name:', shop.CATALOG_BY_ID['admin-case-90']['name'])
print('admin-supply-cooling-fluid:', shop.CATALOG_BY_ID['admin-supply-cooling-fluid']['name'])
print('admin-supply-gpu-chip:', shop.CATALOG_BY_ID['admin-supply-gpu-chip']['name'])
ids = [c['id'] for c in shop.CATALOG]
print('unique ids:', len(set(ids)) == len(ids))
