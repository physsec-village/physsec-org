import xmlrpc.client
import os 
db = os.getenv("ODOO_DB")
url = os.getenv("ODOO_URL")
username = os.getenv("ODOO_USER")
api_key = os.getenv("ODOO_API_KEY")

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, api_key, {})

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

inventory = models.execute_kw(
    db, uid, api_key,
    'stock.quant', 'search_read',
    [[]],
    {
        'fields': ['product_id', 'location_id', 'quantity'],
        'limit': 1000
    }
)

print(inventory)