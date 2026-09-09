import os, sys
sys.path.insert(0, '.')
os.environ.setdefault('JWT_SECRET', 'test')
import assets
print('admin-re-1 in CATALOG_BY_SLUG:', 'admin-re-1' in assets.CATALOG_BY_SLUG)
print('admin-biz-1 in CATALOG_BY_SLUG:', 'admin-biz-1' in assets.CATALOG_BY_SLUG)
print('admin-re-81 in CATALOG_BY_SLUG:', 'admin-re-81' in assets.CATALOG_BY_SLUG)
print('Total admin-re-*:', sum(1 for s in assets.CATALOG_BY_SLUG if s.startswith('admin-re-')))
print('Total admin-biz-*:', sum(1 for s in assets.CATALOG_BY_SLUG if s.startswith('admin-biz-')))
print()
print('Sample admin-re-1 entry:')
e = assets.CATALOG_BY_SLUG.get('admin-re-1')
if e:
    for k, v in e.items():
        print(f'  {k}: {v}')
print()
print('Sample admin-biz-1 entry:')
e = assets.CATALOG_BY_SLUG.get('admin-biz-1')
if e:
    for k, v in e.items():
        print(f'  {k}: {v}')
