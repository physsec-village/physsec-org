from fastapi import APIRouter, Request
from starlette.responses import JSONResponse
from .odoo import get_inventory

router = APIRouter(prefix="/odoo")


@router.get("/inventory", response_class=JSONResponse)
def inventory():
    return get_inventory()