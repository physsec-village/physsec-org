import os
import xmlrpc.client
from dotenv import load_dotenv

load_dotenv()

db = os.getenv("ODOO_DB")
url = os.getenv("ODOO_URL")
username = os.getenv("ODOO_USER")
api_key = os.getenv("ODOO_API_KEY")

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, api_key, {})


models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")



def get_inventory(offset=0, limit=25):

    inventory = models.execute_kw(
        db, uid, api_key,
        'product.product', 'search_read',
        [[]],
        {
            'fields': ['id', 'name', 'default_code', 'list_price', 'qty_available', 'image_1920'],
            "limit": limit,
            "offset": offset
        }
    )
    print(inventory)